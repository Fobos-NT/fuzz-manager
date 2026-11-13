# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################
"""Templates for OSS-Fuzz project files."""

LANGUAGE_TO_BASE_BUILDER_IMAGE = {
    'c': 'base-builder',
    'c++': 'base-builder',
    'go': 'base-builder-go',
    'python': 'base-builder-python',
    'javascript': 'base-builder-javascript',
    'jvm': 'base-builder-jvm',
    'rust': 'base-builder-rust',
    'ruby': 'base-builder-ruby',
    'swift': 'base-builder-swift',
}

INTROSPECTOR_BLOCK = """
### 3.5 Генерация отчета introspector

Для того чтобы сгенерировать отчёт introspector необходимо выполнить:
```bash
fuzz-manager introspector .
```
При этом корпус для обёртки %(target)s  должен находиться в директории ./corpus/%(target)s

Полученный HTML отчёт находится в директории `./out/introspector`
"""

SYDR_C_BUILD_BLOCK = """
Пример сборки для sydr-fuzz (сборка под sydr-fuzz без санитайзеров, под libfuzzer с адресным санитайзером и под afl с санитайзером неопределенного поведения):
```bash
fuzz-manager build_fuzzers --use_separate_dir --engine=sydr-fuzz --sanitizer=none .
fuzz-manager build_fuzzers --use_separate_dir --engine=libfuzzer --sanitizer=address .
fuzz-manager build_fuzzers --use_separate_dir --engine=afl --sanitizer=undefined .
```
"""

SYDR_NO_C_BUILD_BLOCK = """
Пример сборки для sydr-fuzz (сборка под libfuzzer с адресным санитайзером):
```bash
fuzz-manager build_fuzzers --use_separate_dir --engine=libfuzzer --sanitizer=address .
```
"""

HARNESS_EXTENSIONS = {
    'c': 'c', 'c++': 'cpp', 'go': 'go', 'python': 'py', 'rust': 'rs',
    'ruby': 'rb', 'swift': 'swift', 'javascript': 'js', 'jvm': 'java',
}

EXTERNAL_DOCKER_TEMPLATE = """FROM ghcr.io/fobos-nt/fuzz-manager/%(base_builder)s

# TODO: install dependencies
RUN git clone project.git $SRC/project
COPY build.sh $SRC/
COPY assets $SRC/assets
WORKDIR $SRC
"""

EXTERNAL_BUILD_TEMPLATE = """#!/bin/bash -eu
# build project
./autogen.sh || true
./configure || true
make -j$(nproc) || true

# build fuzzers
$CXX $CXXFLAGS $SRC/assets/%(target)s/%(target)s_fuzz.%(fuzz_ext)s -o $OUT/%(target)s \\
    $LIB_FUZZING_ENGINE

cp -r $SRC/assets/*/* $OUT 
zip -j $OUT/%(target)s_seed_corpus.zip $SRC/assets/%(target)s/%(target)s_seed_corpus/*"""

EXTERNAL_PROJECT_YAML_TEMPLATE = """language: %(language)s"""

EXTERNAL_README_TEMPLATE = """
# Fuzzing %(project_name)s_fuzz

## 1. ЦЕЛЬ

Объектом фаззинг-тестирования является программный компонент `%(project_name)s`. 
<!--Кратко опишите програмный компонент. `%(project_name)s` — это ... .-->

Язык программирования: `%(language)s`.

Версия объекта: <!--Заполните версию объекта-->

Платформа тестирования: <!--Заполните платформу, в которой проводиться тестирование, например `linux/amd64`-->

Границы тестирования: <!--Опишите в какой функционал тестируется-->

## 2. ОПИСАНИЕ

### 2.1 Поверхность атаки и обоснование выбора целей
<!-- Опишите ПА и входную точку для фаззинга и обоснуйте выбор цели -->

<!-- Анализ исходного кода компонента показал, что ... 
     В качестве входной точки для фаззинга был выбран класс ... -->

### 2.2 Модель нарушителя и контролируемые входные данные
<!--Опишите ПА и входную точку для фаззинга и обоснуйте выбор цели-->

<!--В качестве потенциального нарушителя выбран ...-->

### 2.3 Методика и инструментарий
<!--Опишите методику фаззинг тестирования и инструментарий -->

<!--Например:
    Фаззинг проводился с использованием ...
    Дефекты детектируются по необработанным исключениям, зависаниям и превышению лимитов памяти/времени.
    Собиралось покрытие кода и формировался собственный корпус; артефакты выполнения сохранялись.-->

### 2.4 Обёртка (harness) и окружение
<!--Опишите обертку:
                   - основной принцип её работы,
                   - использованные подходы по минимизации недетерменированного поведения,
                   - использованные принципы препятствующие накоплению глобального состояния между итерациями-->

Исходный текст фаззинг-обёртки находится в файле `/%(project_name)s/assets/%(target)s/%(target)s_fuzz.%(fuzz_ext)s`.

### 2.5 Преодоление блокирующих падений
<!--Опишите выявлены ли блокирующие падения
    Если выявлены блокирующие падения, опишите меры, принятые для устранения-->

## 3. Инструкция по запуску

### 3.1 Подготовка окружения

Все приведённые команды выполняются с помощью вспомогатьльного скрипта infra/helper.py, который входит в [fuzz-manager репозиторий](https://github.com/Fobos-NT/fuzz-manager/blob/master/infra/helper.py).

Перед началом работы необходимо склонировать себе fuzz-manager репозиторий:

```bash
git clone --depth 1 https://github.com/Fobos-NT/fuzz-manager.git
```

Для простоты использования можно создать символьную ссылку на helper.py
```
ln -s /path/to/helper.py /usr/bin/fuzz-manager
```

При выполнении команд из `infra/helper.py` необходимо находиться в корневой директории проекта.

1. Подготовка сборок для фаззинга

* Если вы планируете использовать sydr-fuzz, нужно собрать проект под нужные фаззинг-движки и санитайзеры с указанием флага `--use_separate_dir`.

* Если sydr-fuzz не используется, то необходимо делать только одну сборку под конкретный фаззинг-движок и санитайзер.

Пример сборки для libfuzzer с адрессным санитайзером:
```bash
fuzz-manager build_fuzzers --engine=libfuzzer --sanitizer=address .
```
%(sydr_build_block)s
**Доступные engines:** `libfuzzer`, `afl`, `sydr-fuzz`, `honggfuzz`, `centipede`, `none`, `wycheproof`

**Доступные sanitizers:** `address` (default), `none`, `memory`, `undefined`, `thread`, `coverage`, `introspector`, `hwaddress`

### 3.2.1 Запуск фаззинга при помощи sydr-fuzz

1. Чтобы запустить фаззинг при помощи `sydr-fuzz`:
```bash
SYDR_PATH={path_to_sydr-fuzz} fuzz-manager run_fuzzer --engine=sydr-fuzz . %(target)s
```
Есть возможность выставлять таймаут фаззинга через флаг `--timeout`, менять количество потоков через флаг `--workers`, а также отключать минимизацию корпуса через флаг `--no_cmin`. 

С остальными флагами можно ознакомиться с помощью `help`.

Наработанный корпус находится в директории `./out/%(target)s_out`

### 3.2.2 Запуск фаззинга без sydr-fuzz

1. Для запуска фаззинга %(target)s перед каждой фаззинг итерацией необходимо собирать сборку под конкретный фаззинг-движок и с конкретным санитайзером. Например, для сборки для libfuzzer без санитайзеров:
```bash
fuzz-manager build_fuzzers --engine=libfuzzer --sanitizer=address .
fuzz-manager run_fuzzer . %(target)s
```
Есть возможность выставлять таймаут фаззинга через флаг `--timeout`, менять количество потоков через флаг `--workers`, а также отключать минимизацию корпуса через флаг `--no_cmin`. 

С остальными флагами можно ознакомиться с помощью `help`.

Наработанный корпус находится в директории `./out/%(target)s_out`

### 3.3 Обработка падений с помощью casr 

Чтобы произвести обработку падений с помощью casr. При этом все найденные креши должны находиться в директории `./crashes/%(target)s`.
```bash
fuzz-manager casr --fuzz-target %(target)s --no-crashes-download .
```
### 3.4 Сбор покрытия:

1. Для того чтобы собрать покрытие, сначала нужно сделать сборку проекта для покрытия:
```bash
fuzz-manager build_fuzzers --engine=libfuzzer --sanitizer=coverage .
```

2. После этого запускаем сбор покрытия. При этом корпус для обёртки %(target)s  по умолчанию берётся из директории ./corpus/%(target)s, но есть возможность использовать флаг --corpus-dir=./out/%(target)s_out/
```bash
fuzz-manager coverage . --fuzz-target=%(target)s
```

Сгенерированный общий HTML отчёт о покрытии находится в директории `./out/report/linux`. HTML отчёт о покрытии для конкретной обёртки находится по пути `./out/report_target/%(target)s/linux`
%(introspector_block)s

## 4. РЕЗУЛЬТАТЫ

### 4.1 Условия запуска
<!--Опишите как запускался фаззинг-->

<!--Например:
             Фаззинг запускался для каждой обёртки на 10 часов (36000 секунд). 
             Фаззинг запускался с использованием sydr-fuzz.--> 

Для автоматизации всех стадий фаззинг-процесса использовался fuzz-manager.

### 4.2 Обнаруженные дефекты

<!--Опишите обнаруженные дефекты-->

### 4.3 Воздействие с апстримом

<!--Опишите было ли взаимодействие с апстримом-->

## 5. ФАЙЛЫ

В качестве артефактов предоставляются 3 архива:
1. `%(project_name)s_src.tar.gz` - архив с исходниками проекта по фаззингу. Содержит исходный код обёртки `%(target)s_fuzz.%(fuzz_ext)s`, начальный seed корпус для фаззинга, `Dockerfile` с подготовленным окружением и `build.sh` - скрипт по сборке проекта.
2. `coverage.tar.gz` - HTML-отчёт о наработанном покрытии кода.
3. `fuzz_out.tar.gz` - архив с выходной директорией фаззера sydr-fuzz. Содержит наработанный корпус `./corpus`, логи запуска фаззинга `sydr-fuzz.log`.
"""

EXTERNAL_CI_CD_TEMPLATE = """include:
  - project: 'fuzz_group/fuzz-manager'
    ref: main
    file: '/ci_cd_templates/fuzz_manager_c_ci.yml'

variables:
  FUZZ_TARGET: "%(target)s"
  FUZZ_TIME: "100"
"""

PROJECT_GITIGNORE_TEMPLATE = "/out\n/work\n"

TEMPLATES = {
    'build.sh': EXTERNAL_BUILD_TEMPLATE,
    'Dockerfile': EXTERNAL_DOCKER_TEMPLATE,
    'project.yaml': EXTERNAL_PROJECT_YAML_TEMPLATE,
    'README.md': EXTERNAL_README_TEMPLATE,
    '.gitlab-ci.yml': EXTERNAL_CI_CD_TEMPLATE,
    '.gitignore': PROJECT_GITIGNORE_TEMPLATE,
}

TARGET_DICTIONARY_TEMPLATE = "# Dictionary file\n"
