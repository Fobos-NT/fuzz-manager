#!/usr/bin/env python3

import os
import requests
import gitlab
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from dataclasses import dataclass


# default runner count
RUNNER_COUNT = 5

@dataclass
class ProjectInfo:
    id: int
    name: str
    path_with_namespace: str
    web_url: str
    main_branch_exists: bool
    has_gitlab_ci_file: bool
    last_modified: Optional[datetime]
    last_pipeline_run: Optional[datetime]
    pipeline_run_count: int
    default_branch: str

class FuzzingPipelineScheduler:
    def __init__(self, gitlab_url: str, private_token: str, group_id: int, dd_token: str, dd_url: str):
        """
        Инициализация планировщика
        :param gitlab_url: URL GitLab инстанса
        :param private_token: Personal Access Token (права: read_api, read_repository, write_repository)
        :param group_id: ID группы проектов для фаззинга
        """
        self.gl = gitlab.Gitlab(gitlab_url, private_token=private_token)
        self.group_id = group_id
        self.group = self.gl.groups.get(group_id)
        
        # defectdojo params
        self.dd_token = dd_token
        self.dd_url = dd_url

        self.running_pipelines = []

        self.weights = {
            'last_change': 0.3,
            'runs_count': 0.2,
            'defects': 0.4
        }

    def get_fuzzing_projects(self) -> List[ProjectInfo]:
        result: List[ProjectInfo] = []
        # the list of projects to exclude
        exceptions = ["fuzz-manager"]
        # Получаем проекты группы
        group = self.gl.groups.get(self.group_id, lazy=True)
        all_projects = group.projects.list(include_subgroups=True, all=True)

        for project_stub in all_projects:
            try:
                project = self.gl.projects.get(project_stub.id)
                # skip excluded projects
                if project.name in exceptions:
                    continue
                default_branch = project.default_branch or "main"
                main_branch_exists = True
                has_gitlab_ci_file = False
                last_modified = None
                last_pipeline_run = None
                pipeline_run_count = 0

                
                try:
                    # Проверяем существование ветки по умолчанию
                    # Теперь project - полный объект, у него есть branches
                    project.branches.get(default_branch)
                    main_branch_exists = True
                    
                    # Проверяем наличие .gitlab-ci.yml в той же ветке
                    try:
                        project.files.get(file_path=".gitlab-ci.yml", ref=default_branch)
                        has_gitlab_ci_file = True
                    except gitlab.exceptions.GitlabGetError:
                        pass
                
                except gitlab.exceptions.GitlabGetError:
                    main_branch_exists = False

                # Получаем данные только если ветка существует
                if main_branch_exists:
                    # Получаем последний коммит
                    try:
                        commits = project.commits.list(ref_name=default_branch, per_page=1, get_all=False)
                        if commits:
                            last_modified = datetime.strptime(commits[0].committed_date, "%Y-%m-%dT%H:%M:%S.%f%z")
                    except Exception as e:
                        print(f"Error getting commits for project {project.id}: {e}")

                    # Получаем информацию о пайплайнах - один запрос для получения и количества, и последнего
                    try:
                        # Получаем пайплайны с ограничением, но с информацией о пагинации
                        pipelines = project.pipelines.list(ref=default_branch, order_by="updated_at", 
                                                        sort="desc", per_page=100, get_all=False)

                        for pipe in pipelines:
                            if (pipe.status == 'running'):
                                self.running_pipelines.append(pipe)
                        
                        if pipelines:
                            last_pipeline_run = datetime.strptime(pipelines[0].updated_at, "%Y-%m-%dT%H:%M:%S.%f%z")
                            pipeline_run_count = len(pipelines)
                            
                            # Если получили максимальное количество (100), значит пайплайнов больше
                            # Делаем дополнительный запрос только в этом случае
                            if len(pipelines) == 100:
                                try:
                                    # Получаем только количество через быстрый запрос
                                    all_pipelines_count = project.pipelines.list(ref=default_branch, page=1, per_page=1, get_all=False)
                                    # В некоторых версиях python-gitlab можно получить total из pagination
                                    if hasattr(all_pipelines_count, 'pagination') and 'total' in all_pipelines_count.pagination:
                                        pipeline_run_count = all_pipelines_count.pagination['total']
                                    else:
                                        # Альтернативный способ - получаем только первую страницу для подсчета
                                        pipeline_run_count = len(project.pipelines.list(ref=default_branch, get_all=True))
                                except Exception as e:
                                    print(f"Error counting pipelines for project {project.id}: {e}")
                                    # Оставляем приблизительное количество
                                    pipeline_run_count = len(pipelines)
                    except Exception as e:
                        print(f"Error getting pipelines for project {project.id}: {e}")

                result.append(ProjectInfo(
                    id=project.id,
                    name=project.name,
                    path_with_namespace=project.path_with_namespace,
                    web_url=project.web_url,
                    main_branch_exists=main_branch_exists,
                    has_gitlab_ci_file=has_gitlab_ci_file,
                    last_modified=last_modified,
                    last_pipeline_run=last_pipeline_run,
                    pipeline_run_count=pipeline_run_count,
                    default_branch=default_branch,
                ))
                
            except Exception as e:
                print(f"Error processing project {project.id}: {e}")
                continue

        return result

    def project_ready(self, project: ProjectInfo) -> bool:
        """Проверка, готов ли проект к запуску пайплайна"""
        return project.main_branch_exists and project.has_gitlab_ci_file

    def get_defect_count(self, project: ProjectInfo) -> int:
        """
        Получение количества открытых дефектов из DefectDojo для проекта.
        Выполняется только если настроен API токен DefectDojo.
        """

        url = self.dd_url.rstrip('/')
        headers = {'Authorization': f'Token {self.dd_token}'}

        try:
            resp = requests.get(f"{url}/api/v2/products/", headers=headers, params={'name': project.name})
            resp.raise_for_status()
            data = resp.json()
            if data['count'] == 0:
                return 0

            product_id = data['results'][0]['id']
            resp_find = requests.get(f"{url}/api/v2/findings/", headers=headers, params={
                'test__engagement__product': product_id,
                'active': 'true',
                'limit': '1'
            })
            resp_find.raise_for_status()
            return resp_find.json()['count']
        except Exception:
            return 0

    def normalize(self, values: List[float]) -> List[float]:
        """Нормализация значений от 0 до 1"""
        if not values:
            return []
        min_v, max_v = min(values), max(values)
        if min_v == max_v:
            return [0.5 for _ in values]
        return [(v - min_v) / (max_v - min_v) for v in values]
        
    def prioritize_projects(self, projects: List[ProjectInfo]) -> List[ProjectInfo]: 
        now = datetime.now(timezone.utc)
        filtered_projects = []
        last_changes = []
        run_counts = []
        defect_counts = []

        # Фильтрация и сбор данных
        for p in projects:
            if not self.project_ready(p):
                continue

            if p.last_pipeline_run and now - p.last_pipeline_run < timedelta(hours=24):
                continue

            defect_count = 0
            if self.dd_url and self.dd_token:
                defect_count = self.get_defect_count(p)

            filtered_projects.append(p)
            last_changes.append((now - p.last_modified).total_seconds())
            run_counts.append(p.pipeline_run_count)
            defect_counts.append(defect_count)

        if not filtered_projects:
            return []

        # Нормализация: чем выше значение — тем выше приоритет
        norm_last_change = self.normalize(last_changes)
        norm_runs_count = [1 - x for x in self.normalize(run_counts)]  # меньше запусков — выше приоритет 
        norm_defects = self.normalize(defect_counts)

        # Расчет итогового приоритета
        scored_projects = []
        for i, p in enumerate(filtered_projects):
            score = (
                norm_last_change[i] * self.weights['last_change'] +
                norm_runs_count[i] * self.weights['runs_count'] +
                norm_defects[i] * self.weights['defects']
            )
            scored_projects.append((score, p))

        # Сортировка по убыванию приоритета
        scored_projects.sort(reverse=True, key=lambda x: x[0])
        return [p for _, p in scored_projects]
    
    def get_available_runners(self) -> int:
        available_counter = 0
        try:
            runners = self.group.runners.list(all=True)
            for r in runners:
                try:
                    runner = self.gl.runners.get(r.id)
                    if (
                        runner.runner_type == 'group_type' and
                        runner.active and
                        runner.online and # не знает занят ли раннер
                        any(g['id'] == self.group_id for g in runner.groups)
                    ):
                        available_counter += 1
                except Exception as e:
                    print(f"Ошибка при получении статуса раннера {r.id}: {e}")
                    continue
        except Exception as e:
            print(f"Ошибка при запросе раннеров: {e}")
            print(f"Используем значение по умолчанию для количества раннеров (переменная окружения RUNNER_COUNT): {RUNNER_COUNT}")
            available_counter = RUNNER_COUNT
        
        print(f"Доступных раннеров: {available_counter}")
        return available_counter


    def run_pipelines(self, prioritized_projects: List[ProjectInfo], available_runners_count: int) -> None:
        if available_runners_count == 0:
            print("Нет доступных раннеров для запуска пайплайнов.")
            return

        # get the max number of cuncurent pipilines
        # leave several (5) runners free just in case
        max_parallel = available_runners_count - len(self.running_pipelines) - 8
        started = 0

        for running_pipe in self.running_pipelines:
            print(f"Запущенный пайплайн: {running_pipe.web_url}")

        for project in prioritized_projects:
            if started >= max_parallel:
                print("Все доступные раннеры заняты, остальные проекты будут запущены позже.")
                break

            try:
                p = self.gl.projects.get(project.id)
                print(f"Запуск пайплайна для проекта: {project.name} ({project.default_branch})")
                # run fuzzing for eight hours for now. Change that in the future
                pipeline = p.pipelines.create({'ref': project.default_branch, 'variables': [{'key': 'FUZZ_TIME', 'value': '10h'},]})
                print(f"Создан пайплайн #{pipeline.id} {pipeline.web_url}")
                started += 1
            except gitlab.exceptions.GitlabCreateError as e:
                print(f"Ошибка при запуске пайплайна для {project.name}: {e.error_message}")
            except Exception as e:
                print(f"Не удалось запустить пайплайн для {project.name}: {e}")

    def schedule_pipelines(self) -> None:
        print("Планирование запусков пайплайнов...")

        # Шаг 2: Получение проектов
        projects = self.get_fuzzing_projects()
        if not projects:
            print("Нет доступных проектов в группе.")
            return

        # Шаг 3: Приоритезация проектов
        prioritized_projects = self.prioritize_projects(projects)
        if not prioritized_projects:
            print("Нет проектов, удовлетворяющих условиям для запуска.")
            return

        print("Выбранные проекты для запуска (по убыванию)")
        for i, project in enumerate(prioritized_projects):
            print(str(i) + ") " + project.name)
        print()

        # Шаг 4: Запуск пайплайнов
        self.run_pipelines(prioritized_projects, self.get_available_runners())

if __name__ == "__main__":
    GITLAB_URL = os.getenv("GITLAB_URL")
    PRIVATE_TOKEN = os.getenv("PRIVATE_TOKEN")
    GROUP_ID = int(os.getenv("GROUP_ID")) # ID фаззинг группы

    DD_TOKEN = os.getenv("DD_TOKEN")
    DD_URL = os.getenv("DOJO_URL")

    # if RUNNER_COUNT env is not set return default value
    RUNNER_COUNT = os.getenv("RUNNER_COUNT", default=RUNNER_COUNT)
    
    if not DD_TOKEN or not DD_URL:
        print("Параметры для DefectDojo не были установлены. Мы не будем учитывать имеющиеся падения при приоритизации фаззинг-проектов")

    scheduler = FuzzingPipelineScheduler(
        gitlab_url=GITLAB_URL,
        private_token=PRIVATE_TOKEN,
        group_id=GROUP_ID,
        dd_token=DD_TOKEN,
        dd_url=DD_URL
    )
    
    # Запуск планировщика
    scheduler.schedule_pipelines()
