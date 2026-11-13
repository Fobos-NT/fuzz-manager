#!/usr/bin/env python3
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

# Modified by fuzz-manager from original OSS-Fuzz source.

"""Helper script for OSS-Fuzz users. Can do common tasks like building
projects/fuzzers, running them etc."""

from __future__ import print_function
from multiprocessing.dummy import Pool as ThreadPool
import argparse
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys

import constants
import templates
# import pipeline_scheduler

# Nexus url address
REPOSITORY_BASE_URL = "http://10.10.10.10:8080"
# Nexus repository name to work with
REPOSITORY_NAME = "fuzzing_test"
# Tree structure to use inside of repository to save and download artifacts
REPOSITORY_PROJECT_PATH = "/fuzzing/{project}/"

# Template url for downloading artifacts for a project
REPOSITORY_DOWNLOAD_URL_TEMPLATE = f"{REPOSITORY_BASE_URL}/repository/{REPOSITORY_NAME}/{REPOSITORY_PROJECT_PATH}/" + "{archive_filename}"

# Template url for uploading artifacts for a project
REPOSITORY_UPLOAD_URL = f"{REPOSITORY_BASE_URL}/service/rest/v1/components?repository={REPOSITORY_NAME}"

def _download_archive(project_name: str, archive_filename: str, output_file: str) -> bool:
    """
    download archive_filename from Nexus repository for project_name and save it to output_file
    """

    download_url = REPOSITORY_DOWNLOAD_URL_TEMPLATE.format(
        project=project_name,
        archive_filename=archive_filename,
    )

    cmd = ["wget", "-O", output_file]

    # get NEXUS_USER and NEXUS_TOKEN environment variables
    user, password = _get_artifact_repository_user()
    if user == None or password==None:
      return False
    cmd += ["--user", user, "--password", password, download_url]

    try:
        with open(os.devnull, "w") as stdout:
            subprocess.check_call(cmd, stdout=stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to download %s (exit code %d).", download_url, e.returncode)
        return False
    except OSError:
        logger.error("Failed to download %s", download_url)
        return False


def _upload_archive(project_name: str, archive_path: str, archive_filename: str) -> bool:
    """
    upload archive_filename located at archive_path to Nexus repository for project_name
    """

    # get NEXUS_USER and NEXUS_TOKEN environment variables
    user, password = _get_artifact_repository_user()
    if user == None or password==None:
      return False
    auth = ["-u", f"{user}:{password}"]

    cmd = [
        "curl", *auth,
        "-F", f"raw.directory={REPOSITORY_PROJECT_PATH.format(project=project_name)}",
        "-F", f"raw.asset1=@{archive_path}",
        "-F", f"raw.asset1.filename={archive_filename}",
        "-X", "POST", REPOSITORY_UPLOAD_URL,
    ]

    try:
        with open(os.devnull, "w") as stdout:
            subprocess.check_call(cmd, stdout=stdout)
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        logger.error("Failed to upload to Nexus: %s", e)
        return False

OSS_FUZZ_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BUILD_DIR = os.path.join(OSS_FUZZ_DIR, 'build')

CONTAINER_REGISTRY_PATH = 'ghcr.io/fobos-nt/fuzz-manager/'
BASE_RUNNER_IMAGE = 'ghcr.io/fobos-nt/fuzz-manager/base-runner'

def _get_base_runner_image(args, debug=False):
  """Returns the base runner image to use."""
  image = BASE_RUNNER_IMAGE
  if debug:
    image += '-debug'

  tag = 'latest'
  if hasattr(args, 'base_image_tag') and args.base_image_tag:
    tag = args.base_image_tag
  elif hasattr(args, 'project') and args.project:
    if args.project.base_os_version != 'legacy':
      tag = args.project.base_os_version

  return f'{image}:{tag}'

BASE_IMAGES = {
    'generic': [
        f'{CONTAINER_REGISTRY_PATH}/base-image',
        f'{CONTAINER_REGISTRY_PATH}/base-clang',
        f'{CONTAINER_REGISTRY_PATH}/base-builder',
        BASE_RUNNER_IMAGE,
        f'{CONTAINER_REGISTRY_PATH}/base-runner-debug',
    ],
    'go': [f'{CONTAINER_REGISTRY_PATH}/base-builder-go'],
    'javascript': [f'{CONTAINER_REGISTRY_PATH}/base-builder-javascript'],
    'jvm': [f'{CONTAINER_REGISTRY_PATH}/base-builder-jvm'],
    'python': [f'{CONTAINER_REGISTRY_PATH}/base-builder-python'],
    'rust': [f'{CONTAINER_REGISTRY_PATH}/base-builder-rust'],
    'ruby': [f'{CONTAINER_REGISTRY_PATH}/base-builder-ruby'],
    'swift': [f'{CONTAINER_REGISTRY_PATH}/base-builder-swift'],
}

BASE_OS_VERSION_REGEX = re.compile(r'\s*base_os_version\s*:\s*([^\s]+)')

VALID_PROJECT_NAME_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')
MAX_PROJECT_NAME_LENGTH = 26

PROJECT_LANGUAGE_REGEX = re.compile(r'\s*language\s*:\s*([^\s]+)')

PROJECT_ENGINE_REGEX = re.compile(r'\s*fuzzing_engine\s*:\s*([^\s]+)')

WORKDIR_REGEX = re.compile(r'\s*WORKDIR\s*([^\s]+)')

# Regex to match special chars in project name.
SPECIAL_CHARS_REGEX = re.compile('[^a-zA-Z0-9_-]')

LANGUAGE_TO_BASE_BUILDER_IMAGE = templates.LANGUAGE_TO_BASE_BUILDER_IMAGE
ARM_BUILDER_NAME = 'oss-fuzz-buildx-builder'

logger = logging.getLogger(__name__)

if sys.version_info[0] >= 3:
  raw_input = input  # pylint: disable=invalid-name

# pylint: disable=too-many-lines


class Project:
  """Class representing a project that is in OSS-Fuzz or an external project
  (ClusterFuzzLite user)."""

  def __init__(
      self,
      project_path,
      build_integration_path=constants.DEFAULT_EXTERNAL_BUILD_INTEGRATION_PATH):

    self.path = os.path.abspath(project_path)
    self.name = os.path.basename(self.path)
    self.build_integration_path = os.path.join(self.path, build_integration_path)

  @property
  def dockerfile_path(self):
    """Returns path to the project Dockerfile."""
    return os.path.join(self.build_integration_path, 'Dockerfile')

  @property
  def mode(self):
    """Select development mounts only through the host environment."""
    mode = os.getenv('FM_MODE', 'work')
    if mode not in ('dev', 'work'):
      raise ValueError('FM_MODE must be dev or work, got %r' % mode)
    return mode

  @property
  def is_dev(self):
    return self.mode == 'dev'

  @property
  def sources(self):
    """Default local source root for development builds."""
    return os.path.join(self.path, 'sources')

  @property
  def language(self):
    """Returns project language."""
    project_yaml_path = os.path.join(self.build_integration_path,
                                     'project.yaml')
    if not os.path.exists(project_yaml_path):
      logger.warning('No project.yaml. Assuming c++.')
      return constants.DEFAULT_LANGUAGE

    with open(project_yaml_path) as file_handle:
      content = file_handle.read()
      for line in content.splitlines():
        match = PROJECT_LANGUAGE_REGEX.match(line)
        if match:
          return match.group(1)

    logger.warning('Language not specified in project.yaml. Assuming c++.')
    return constants.DEFAULT_LANGUAGE

  @property
  def coverage_extra_args(self):
    """Returns project coverage extra args."""
    project_yaml_path = os.path.join(self.build_integration_path,
                                     'project.yaml')
    if not os.path.exists(project_yaml_path):
      logger.warning('project.yaml not found: %s.', project_yaml_path)
      return ''

    with open(project_yaml_path) as file_handle:
      content = file_handle.read()

    coverage_flags = ''
    read_coverage_extra_args = False
    # Pass the yaml file and extract the value of the coverage_extra_args key.
    # This is naive yaml parsing and we do not handle comments at this point.
    for line in content.splitlines():
      if read_coverage_extra_args:
        # Break reading coverage args if a new yaml key is defined.
        if len(line) > 0 and line[0] != ' ':
          break
        coverage_flags += line
      if 'coverage_extra_args' in line:
        read_coverage_extra_args = True
        # Include the first line only if it's not a multi-line value.
        if 'coverage_extra_args: >' not in line:
          coverage_flags += line.replace('coverage_extra_args: ', '')
    return coverage_flags

  @property
  def fuzzing_engine(self):
    """Returns project fuzzing engine."""
    project_yaml_path = os.path.join(self.build_integration_path,
                                     'project.yaml')
    if not os.path.exists(project_yaml_path):
      logger.warning('project.yaml not found: %s.', project_yaml_path)
      return ''

    with open(project_yaml_path) as file_handle:
      content = file_handle.read()
      for line in content.splitlines():
        match = PROJECT_ENGINE_REGEX.match(line)
        if match:
          engine = match.group(1)
          if engine in constants.ENGINES:
            return engine

          logger.warning(f'Unknown fuzzing_engine specified. Available values: {constants.ENGINES}')
          return False

    logger.warning(f'fuzzing_engine not specified in project.yaml. Assuming {constants.DEFAULT_ENGINE}')
    return False

  @property
  def base_os_version(self):
    """Returns the project's base OS version."""
    project_yaml_path = os.path.join(self.build_integration_path,
                                     'project.yaml')
    if not os.path.exists(project_yaml_path):
      return 'legacy'

    with open(project_yaml_path) as file_handle:
      content = file_handle.read()
      for line in content.splitlines():
        match = BASE_OS_VERSION_REGEX.match(line)
        if match:
          return match.group(1)

    return 'legacy'

  @property
  def out(self):
    """Returns the out dir for the project. Creates it if needed."""
    return _get_out_dir(self.path)

  @property
  def work(self):
    """Returns the out dir for the project. Creates it if needed."""
    return _get_project_build_subdir(self.path, 'work')

  @property
  def corpus(self):
    """Returns the out dir for the project. Creates it if needed."""
    return _get_project_build_subdir(self.path, 'corpus')
  
  @property
  def crashes(self):
    """Returns the crashes dir for the project. Creates it if needed."""
    return _get_project_build_subdir(self.path, 'crashes')

  @property
  def cov_report(self):
    """Returns the coverage report dir for the project. Creates it if needed."""
    return _get_project_build_subdir(self.path, 'cov_report')
  
  @property
  def casr_out(self):
    """Returns the out dir for casr. Creates it if needed."""
    return _get_project_build_subdir(self.out, 'casr_out')

  def fuzzing_out(self, fuzzer):
    """Returns the artifacts dir for the project. Creates it if needed."""
    artifacts_dir = f'{fuzzer}_out'
    return _get_project_build_subdir(self.out, artifacts_dir)

def main():  # pylint: disable=too-many-branches,too-many-return-statements
  """Gets subcommand from program arguments and does it. Returns 0 on success 1
  on error."""
  logging.basicConfig(level=logging.INFO)
  parser = get_parser()
  args = parse_args(parser)

  # Need to do this before chdir.
  # TODO(https://github.com/google/oss-fuzz/issues/6758): Get rid of chdir.
  if hasattr(args, 'testcase_path'):
    args.testcase_path = _get_absolute_path(args.testcase_path)
  # Note: this has to happen after parse_args above as parse_args needs to know
  # the original CWD for external projects.
  # os.chdir(OSS_FUZZ_DIR)
  # if not os.path.exists(BUILD_DIR):
  #   os.mkdir(BUILD_DIR)

  # We have different default values for `sanitizer` depending on the `engine`.
  # Some commands do not have `sanitizer` argument, so `hasattr` is necessary.
  if hasattr(args, 'sanitizer') and not args.sanitizer:
    if args.project.language == 'javascript':
      args.sanitizer = 'none'
    else:
      args.sanitizer = constants.DEFAULT_SANITIZER

  if args.command == 'add_target':
    import project_setup
    result = project_setup.add_target(args)
  elif args.command == 'generate':
    import project_setup
    result = project_setup.generate(args)
  elif args.command == 'build_image':
    result = build_image(args)
  elif args.command == 'build_fuzzers':
    result = build_fuzzers(args)
  elif args.command == 'download_artifacts':
    result = download_artifacts(args)
  elif args.command == 'check_build':
    result = check_build(args)
  elif args.command == 'run_fuzzer':
    result = run_fuzzer(args)
  elif args.command == 'coverage':
    result = coverage(args)
  elif args.command == 'casr':
    result = casr(args)
  # elif args.command == 'pipeline_scheduler':
  #   result = run_pipeline_scheduler(args)
  elif args.command == 'introspector':
    result = introspector(args)
  elif args.command == 'reproduce':
    result = reproduce(args)
  elif args.command == 'shell':
    result = shell(args)
  elif args.command == 'pull_images':
    result = pull_images()
  else:
    # Print help string if no arguments provided.
    parser.print_help()
    result = False
  return bool_to_retcode(result)


def bool_to_retcode(boolean):
  """Returns 0 if |boolean| is Truthy, 0 is the standard return code for a
  successful process execution. Returns 1 otherwise, indicating the process
  failed."""
  return 0 if boolean else 1


def parse_args(parser, args=None):
  """Parses |args| using |parser| and returns parsed args. Also changes
  |args.build_integration_path| to have correct default behavior."""
  # Use default argument None for args so that in production, argparse does its
  # normal behavior, but unittesting is easier.
  parsed_args = parser.parse_args(args)
  project = getattr(parsed_args, 'project', None)
  if not project:
    return parsed_args

  # Use hacky method for extracting attributes so that ShellTest works.
  # TODO(metzman): Fix this.
  parsed_args.project = Project(parsed_args.project)
  try:
    parsed_args.project.mode
  except ValueError as error:
    parser.error(str(error))
  if getattr(parsed_args, 'source_path', None) and not parsed_args.project.is_dev:
    parser.error('source_path requires FM_MODE=dev; work uses sources from the image')
  if (hasattr(parsed_args, 'source_path') and not parsed_args.source_path
      and parsed_args.project.is_dev and not is_base_image(parsed_args.project.name)):
    parsed_args.source_path = parsed_args.project.sources
  return parsed_args


def get_parser():  # pylint: disable=too-many-statements,too-many-locals
  """Returns an argparse parser."""
  parser = argparse.ArgumentParser('helper.py', description='oss-fuzz helpers')
  subparsers = parser.add_subparsers(dest='command')

  generate_parser = subparsers.add_parser('generate', help='Initialize a fuzzing project.')
  generate_parser.add_argument('project', nargs='?', default='.')
  generate_parser.add_argument('--language', default=constants.DEFAULT_LANGUAGE,
                               choices=LANGUAGE_TO_BASE_BUILDER_IMAGE)
  generate_parser.add_argument('--engine', default='sydr-fuzz', choices=constants.ENGINES)
  generate_parser.add_argument('--force', action='store_true', help='Overwrite scaffold files.')
  generate_parser.add_argument('--target', help='Create the first fuzz target and CI template.')

  target_parser = subparsers.add_parser('add_target', help='Add a fuzz target.')
  target_parser.add_argument('name')
  target_parser.add_argument('-C', '--project', default='.')
  target_parser.add_argument('--force', action='store_true', help='Overwrite target templates.')

  build_image_parser = subparsers.add_parser('build_image',
                                             help='Build an image.')
  build_image_parser.add_argument('project')
  build_image_parser.add_argument('--pull',
                                  action='store_true',
                                  help='Attempt to pull all referenced images.')
  _add_architecture_args(build_image_parser)
  build_image_parser.add_argument('--cache',
                                  action='store_true',
                                  default=False,
                                  help='Use docker cache when building image.')
  build_image_parser.add_argument('--no-pull',
                                  action='store_true',
                                  help='Do not pull latest base image.')
  build_image_parser.add_argument('--target',
                                  default="",
                                  choices=["build", "run"],
                                  help='Build target from multistage image.')
  build_image_parser.add_argument('--push',
                                  action='store_true',
                                  default=False,
                                  help='Push run image to container registry')
  build_image_parser.add_argument('--tag', help='Image name. Provide this on push')


  build_fuzzers_parser = subparsers.add_parser(
      'build_fuzzers', help='Build fuzzers for a project.')
  _add_architecture_args(build_fuzzers_parser)
  _add_engine_args(build_fuzzers_parser)
  _add_sanitizer_args(build_fuzzers_parser)
  _add_environment_args(build_fuzzers_parser)
  build_fuzzers_parser.add_argument('project')
  build_fuzzers_parser.add_argument('source_path',
                                    help='local source (dev only; default: <project>/sources/)',
                                    nargs='?')
  build_fuzzers_parser.add_argument('--mount_path',
                                    dest='mount_path',
                                    help='path to mount local source in '
                                    '(defaults to WORKDIR)')
  build_fuzzers_parser.add_argument('--clean',
                                    dest='clean',
                                    action='store_true',
                                    help='clean existing artifacts.')
  build_fuzzers_parser.add_argument('--no-clean',
                                    dest='clean',
                                    action='store_false',
                                    help='do not clean existing artifacts '
                                    '(default).')
  build_fuzzers_parser.set_defaults(clean=False)
  build_fuzzers_parser.add_argument('--build_image_name',
                                    dest='build_image_name',
                                    help='docker build image name to use. '
                                    'Default is {project_name}_build_img')
  build_fuzzers_parser.add_argument('--use_separate_dir',
                                    dest='use_separate_dir',
                                    action='store_true',
                                    help='clean existing artifacts.')
  build_fuzzers_parser.add_argument('--no_build_project_image',
                                    dest='build_project_image',
                                    action='store_false',
                                    help='Do not build project docker image first. Pull image from CR')
  build_fuzzers_parser.add_argument('--push',
                                    action='store_true',
                                    help='Push build artifacts to NEXUS registry. '
                                    'Uses NEXUS_TOKEN and NEXUS_USER environment variable')

  check_build_parser = subparsers.add_parser(
      'check_build', help='Checks that fuzzers execute without errors.')
  _add_architecture_args(check_build_parser)
  _add_engine_args(check_build_parser, choices=constants.ENGINES)
  _add_sanitizer_args(check_build_parser, choices=constants.SANITIZERS)
  _add_environment_args(check_build_parser)
  check_build_parser.add_argument('project',
                                  help='name of the project or path (external)')
  check_build_parser.add_argument('fuzzer_name',
                                  help='name of the fuzzer',
                                  nargs='?')


  run_fuzzer_parser = subparsers.add_parser(
      'run_fuzzer', help='Run a fuzzer in the emulated fuzzing environment.')
  run_fuzzer_parser.add_argument('--run_img', 
                                 help="runtime docker image to use (must inherit from base-runner). "
                                  f"Default is {BASE_RUNNER_IMAGE}")
  run_fuzzer_parser.add_argument('--timeout', help="run fuzzer for a specified period of time (is seconds)")
  run_fuzzer_parser.add_argument('--push_artifacts', help='push artifacts after fuzzing to NEXUS registry.'
                                  ' Uses NEXUS_TOKEN and NEXUS_USER environment variable',
                                  action='store_true')
  run_fuzzer_parser.add_argument('--artifacts_tag', help="add tag to artifacts archive. Usefull to save results for long fuzzing compaign")
  run_fuzzer_parser.add_argument('--no_cmin', help="do not cmin corpus directory after fuzzing", action='store_true')
  run_fuzzer_parser.add_argument('--pull_build', help="pull build artifacts from NEXUS repository. Uses NEXUS_TOKEN and NEXUS_USER environment variables", action='store_true')
  run_fuzzer_parser.add_argument('--pull_artifacts', help="pull previous artifacts from NEXUS repository. Uses NEXUS_TOKEN and NEXUS_USER environment variables", action='store_true')
  run_fuzzer_parser.add_argument('--clean',
                                  dest='clean',
                                  action='store_true',
                                  help="clean existing artifacts.")
  run_fuzzer_parser.add_argument('--workers', dest='workers', type=int, default=1, help="number of cores to use for fuzzing")
  _add_architecture_args(run_fuzzer_parser)
  _add_engine_args(run_fuzzer_parser)
  _add_sanitizer_args(run_fuzzer_parser)
  _add_environment_args(run_fuzzer_parser)
  run_fuzzer_parser.add_argument(
      '--corpus-dir', help='directory to store corpus for the fuzz target')
  run_fuzzer_parser.add_argument('project',
                                 help='name of the project or path (external)')
  run_fuzzer_parser.add_argument('fuzzer_name', help='name of the fuzzer')
  run_fuzzer_parser.add_argument('fuzzer_args',
                                 help='arguments to pass to the fuzzer',
                                 nargs='*')

  coverage_parser = subparsers.add_parser(
      'coverage', help='Generate code coverage report for the project.')
  coverage_parser.add_argument('--no-corpus-download',
                               action='store_true',
                               help='do not download corpus backup from '
                               'remote corpus storage; use corpus located in '
                               '<project>/<fuzz_target>/corpus')
  coverage_parser.add_argument('--fuzz-target',
                               help='specify name of a fuzz '
                               'target to be run for generating coverage '
                               'report')
  coverage_parser.add_argument('--corpus-dir',
                               help='specify location of corpus'
                               ' to be used (requires --fuzz-target argument)')
  coverage_parser.add_argument('--push_artifacts', help='push coverage report to NEXUS registry.'
                                  ' Uses NEXUS_TOKEN and NEXUS_USER environment variable',
                                  action='store_true')
  coverage_parser.add_argument('--artifacts_tag', help="add tag to artifacts archive. Usefull to save results for long fuzzing compaign")
  _add_engine_args(coverage_parser)
  coverage_parser.add_argument('project',
                               help='name of the project or path')
  coverage_parser.add_argument('extra_args',
                               help='additional arguments to '
                               'pass to llvm-cov utility.',
                               nargs='*')
  coverage_parser.add_argument('--pull_build', help="pull build artifacts from NEXUS repository. Uses NEXUS_TOKEN and NEXUS_USER environment variable", action='store_true')
  coverage_parser.add_argument('--run_img', 
                                 help="runtime docker image to use (must inherit"
                                       f"from base-runner). Default is {BASE_RUNNER_IMAGE}")
  _add_architecture_args(coverage_parser)

  casr_parser = subparsers.add_parser('casr', help='triage founded crashes with CASR')
  casr_parser.add_argument('--run_img', 
                                 help=f"runtime docker image to use (must inherit"
                                       "from base-runner). Default is {BASE_RUNNER_IMAGE}")
  casr_parser.add_argument('--crash_dir', help="input directory with founded crashes")
  casr_parser.add_argument('--pull_build', help="pull build artifacts from NEXUS repository. Uses NEXUS_TOKEN and NEXUS_USER environment variable", action='store_true')
  casr_parser.add_argument('--push_artifacts', help='push casr reports to NEXUS registry.'
                                  ' Uses NEXUS_TOKEN and NEXUS_USER environment variable',
                                  action='store_true')
  casr_parser.add_argument('--no-crashes-download',
                               action='store_true',
                               help='do not download crashes backup from '
                               'remote storage; use crashes located in '
                               '<project>/<fuzz_target>/crashes')
  casr_parser.add_argument('--fuzz-target',
                               help='specify name of a fuzz target to triage')

  casr_parser.add_argument('--engine', default=None, choices=constants.ENGINES)
  _add_sanitizer_args(casr_parser)

  casr_parser.add_argument('--dojo-url', help='push founded crashes to DefectDojo url. Must set env DD_TOKEN')
  casr_parser.add_argument('--dojo-product', help='product on DefectDojo to push artifacts. Default is project name')
  casr_parser.add_argument('--dojo-engagement', help='engagement on DefectDojo to push artifacts. Default is target name')
  casr_parser.add_argument('project', help='name of the project or path')

  # pipeline_scheduler_parser = subparsers.add_parser('pipeline_scheduler', help='prioritize projects in a gitlab group for fuzzing')
  # pipeline_scheduler_parser.add_argument('--gitlab_url', required=True, help="url of a gitlab instance")
  # pipeline_scheduler_parser.add_argument('--group_id', required=True, type=int, help="gitlab group id with fuzzing projects")
  # pipeline_scheduler_parser.add_argument('--private_token', help="gitlab glpat private token for the group. Or set GITLAB_FUZZ_TOKEN environment variable")

  introspector_parser = subparsers.add_parser(
      'introspector',
      help='Run a complete end-to-end run of '
      'fuzz introspector. This involves (1) '
      'building the fuzzers with ASAN; (2) '
      'running all fuzzers; (3) building '
      'fuzzers with coverge; (4) extracting '
      'coverage; (5) building fuzzers using '
      'introspector')
  introspector_parser.add_argument('project', help='name of the project')
  introspector_parser.add_argument('--seconds',
                                   help='number of seconds to run fuzzers',
                                   default=10)
  introspector_parser.add_argument('source_path',
                                   help='path of local source',
                                   nargs='?')
  introspector_parser.add_argument(
      '--public-corpora',
      help='if specified, will use public corpora for code coverage',
      default=False,
      action='store_true')
  introspector_parser.add_argument(
      '--private-corpora',
      help='if specified, will use private corpora',
      default=False,
      action='store_true')
  introspector_parser.add_argument('--push_artifacts', help='push introspector report to NEXUS registry.'
                                  ' Uses NEXUS_TOKEN and NEXUS_USER environment variable',
                                  action='store_true')

  download_artifacts_parser = subparsers.add_parser(
      'download_artifacts', help='Download all corpora for a project.')
  download_artifacts_parser.add_argument('--fuzz-target',
                                       help='specify name of a fuzz target')
  download_artifacts_parser.add_argument(
      'project', help='name of the project or path (external)')

  reproduce_parser = subparsers.add_parser('reproduce',
                                           help='Reproduce a crash.')
  reproduce_parser.add_argument('--valgrind',
                                action='store_true',
                                help='run with valgrind')
  reproduce_parser.add_argument('project',
                                help='name of the project or path (external)')
  reproduce_parser.add_argument('fuzzer_name', help='name of the fuzzer')
  reproduce_parser.add_argument('testcase_path', help='path of local testcase')
  reproduce_parser.add_argument('fuzzer_args',
                                help='arguments to pass to the fuzzer',
                                nargs='*')
  _add_environment_args(reproduce_parser)
  _add_architecture_args(reproduce_parser)

  shell_parser = subparsers.add_parser(
      'shell', help='Run /bin/bash within the builder container.')
  shell_parser.add_argument('project',
                            help='name of the project or path (external)')
  shell_parser.add_argument('source_path',
                            help='local source (dev only; default: <project>/sources/)',
                            nargs='?')
  shell_parser.add_argument('--build_image_name',
                            dest='build_image_name',
                            help='docker image name to use instead of building '
                                 '(skip build if image already exists locally)')
  _add_architecture_args(shell_parser)
  _add_engine_args(shell_parser)
  _add_sanitizer_args(shell_parser)


  _add_environment_args(shell_parser)

  subparsers.add_parser('pull_images', help='Pull base images.')
  return parser


def is_base_image(image_name):
  """Checks if the image name is a base image."""
  return os.path.exists(os.path.join('infra', 'base-images', image_name))


def check_project_exists(project):
  """Checks if a project exists."""
  if os.path.exists(project.path):
    return True

  descriptive_project_name = project.path

  logger.error('"%s" does not exist.', descriptive_project_name)
  return False


def _check_fuzzer_exists(project, fuzzer_name, architecture='x86_64'):
  """Checks if a fuzzer exists."""
  platform = 'linux/arm64' if architecture == 'aarch64' else 'linux/amd64'
  command = ['docker', 'run', '--rm', '--platform', platform, '--entrypoint', '']
  command.extend(['-v', '%s:/out' % project.out])
  command.append(BASE_RUNNER_IMAGE)

  command.extend(['/bin/bash', '-c', 'test -f /out/%s' % fuzzer_name])

  try:
    subprocess.check_call(command)
  except subprocess.CalledProcessError:
    logger.error('%s does not seem to exist. Please run build_fuzzers first.',
                 fuzzer_name)
    return False

  return True


def _normalized_name(name):
  """Return normalized name with special chars like slash, colon, etc normalized
  to hyphen(-). This is important as otherwise these chars break local and cloud
  storage paths."""
  return SPECIAL_CHARS_REGEX.sub('-', name).strip('-')


def _get_absolute_path(path):
  """Returns absolute path with user expansion."""
  return os.path.abspath(os.path.expanduser(path))


def _get_command_string(command):
  """Returns a shell escaped command string."""
  return ' '.join(shlex.quote(part) for part in command)


def _get_project_build_subdir(project_path, subdir_name):
  """Creates the |subdir_name| subdirectory of the |project| subdirectory in
  |BUILD_DIR| and returns its path."""
  directory = os.path.join(project_path, subdir_name)
  os.makedirs(directory, exist_ok=True)

  return directory


def _get_out_dir(project_path=''):
  """Creates and returns path to /out directory for the given project (if
  specified)."""
  return _get_project_build_subdir(project_path, 'out')


def _add_architecture_args(parser, choices=None):
  """Adds common architecture args."""
  if choices is None:
    choices = constants.ARCHITECTURES
  parser.add_argument('--architecture',
                      default=constants.DEFAULT_ARCHITECTURE,
                      choices=choices)


def _add_engine_args(parser, choices=None):
  """Adds common engine args."""
  if choices is None:
    choices = constants.ENGINES
  parser.add_argument('--engine',
                      default=constants.DEFAULT_ENGINE,
                      choices=choices)


def _add_sanitizer_args(parser, choices=None):
  """Adds common sanitizer args."""
  if choices is None:
    choices = constants.SANITIZERS
  parser.add_argument('--sanitizer',
                      default=None,
                      choices=choices,
                      help='the default is "address"')


def _add_environment_args(parser):
  """Adds common environment args."""
  parser.add_argument('-e',
                      action='append',
                      help="set environment variable e.g. VAR=value")


def build_image_impl(project, cache=True, pull=False, target="", push=False, tag=None, architecture='x86_64'):
  """Builds target image."""
  project_name = project.name

  if is_base_image(project_name):
    docker_build_dir = os.path.join(OSS_FUZZ_DIR, 'infra', 'base-images',
                                    project_name)
    dockerfile_path = os.path.join(docker_build_dir, 'Dockerfile')
  else:
    if not check_project_exists(project):
      return False
    
    dockerfile_path = project.dockerfile_path
    docker_build_dir = project.path

  build_args = []

  if tag == None:
    target_name = "build" if target == "" else target
    image_name = f'{project_name}_{target_name}_img'
  else:
    image_name = tag

  if architecture == 'aarch64':
    build_args += [
        'buildx',
        'build',
        '--platform',
        'linux/arm64',
        '--progress',
        'plain',
        '--load',
    ]
  if not cache:
    build_args.append('--no-cache')

  if pull:
    build_args.append('--pull')

  build_args += ['-t', image_name, '--file', dockerfile_path]
  if target != "":
    build_args += ['--target', target]
  build_args.append(docker_build_dir)

  if architecture == 'aarch64':
    command = ['docker'] + build_args
    subprocess.check_call(command)
    return True

  if not docker_build(build_args):
    return False

  # only push run image
  if push:
    return docker_push(image_name)
  return True


def _mode_docker_args(project, builder=False):
  """Add live project files in dev without hiding sources baked into /src."""
  args = ['-e', 'FM_MODE=' + project.mode]
  if not project.is_dev or is_base_image(project.name):
    return args

  assets = os.path.join(project.build_integration_path, 'assets')
  if os.path.isdir(assets):
    args += ['-v', assets + ':/src/assets']
  if builder:
    build_script = os.path.join(project.build_integration_path, 'build.sh')
    if os.path.isfile(build_script):
      args += ['-v', build_script + ':/src/build.sh']
  return args


def _env_to_docker_args(env_list):
  """Turns envirnoment variable list into docker arguments."""
  return sum([['-e', v] for v in env_list], [])


def _source_docker_args(project, source_path=None, mount_path=None):
  if not project.is_dev:
    if source_path:
      raise ValueError('source_path requires FM_MODE=dev')
    return []
  if is_base_image(project.name) and not source_path:
    return []
  source = _get_absolute_path(source_path or project.sources)
  if not os.path.isdir(source):
    raise ValueError('Local source directory does not exist: %s' % source)

  if source == project.sources and not mount_path:
    repositories = sorted(
        name for name in os.listdir(source)
        if not name.startswith('.') and os.path.isdir(os.path.join(source, name)))
    if not repositories:
      logger.warning('No source directories found in: %s', source)
      return []
    return sum(([
        '-v', '%s:/src/%s' % (os.path.join(source, name), name)
    ] for name in repositories), [])

  destination = mount_path
  if not destination:
    destination = '/src/' + os.path.basename(source)
  destination = os.path.normpath(destination)
  if not os.path.isabs(destination):
    raise ValueError('Container mount path must be absolute: %s' % destination)
  return [
      '-v', '%s:%s' % (source, destination),
  ]


def workdir_from_lines(lines, default='/src'):
  """Gets the WORKDIR from the given lines."""
  for line in reversed(lines):  # reversed to get last WORKDIR.
    match = re.match(WORKDIR_REGEX, line)
    if match:
      workdir = match.group(1)
      workdir = workdir.replace('$SRC', '/src')

      if not os.path.isabs(workdir):
        workdir = os.path.join('/src', workdir)

      return os.path.normpath(workdir)

  return default


def _workdir_from_dockerfile(project):
  """Parses WORKDIR from the Dockerfile for the given project."""
  with open(project.dockerfile_path) as file_handle:
    lines = file_handle.readlines()

  return workdir_from_lines(lines, default=os.path.join('/src', project.name))


def docker_run(run_args, print_output=True, architecture='x86_64'):
  """Calls `docker run`."""
  platform = 'linux/arm64' if architecture == 'aarch64' else 'linux/amd64'
  command = [
      'docker', 'run', '--shm-size=2g', '--platform', platform
  ]
  if os.getenv('OSS_FUZZ_SAVE_CONTAINERS_NAME'):
    command.append('--name')
    command.append(os.getenv('OSS_FUZZ_SAVE_CONTAINERS_NAME'))
  else:
    command.append('--rm')

  # Support environments with a TTY.
  if sys.stdin.isatty():
    command.append('-i')

  command.extend(run_args)

  logger.info('Running: %s.', _get_command_string(command))
  stdout = None
  if not print_output:
    stdout = open(os.devnull, 'w')

  try:
    subprocess.check_call(command, stdout=stdout, stderr=subprocess.STDOUT)
  except subprocess.CalledProcessError:
    return False

  return True


def docker_build(build_args):
  """Calls `docker build`."""
  command = ['docker', 'build']
  command.extend(build_args)
  logger.info('Running: %s.', _get_command_string(command))

  try:
    subprocess.check_call(command)
  except subprocess.CalledProcessError:
    logger.error('Docker build failed.')
    return False

  return True


def docker_image_exists(image):
  """Check if a docker image already exists locally."""
  command = ['docker', 'image', 'inspect', image]
  try:
    subprocess.check_call(command, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    return True
  except subprocess.CalledProcessError:
    return False


def docker_pull(image):
  """Pull the latest version of a docker image."""
  command = ['docker', 'pull', image]
  logger.info('Running: %s', _get_command_string(command))

  try:
    subprocess.check_call(command)
  except subprocess.CalledProcessError:
    logger.error('Docker pull failed.')
    return False
  return True

def docker_push(image):
  """Call `docker push`."""
  command = ['docker', 'push', image]
  logger.info('Pushing: %s', _get_command_string(command))
  
  try:
    subprocess.check_call(command)
  except subprocess.CalledProcessError:
    logger.error('Docker push failed. Make sure to make docker login\
                 before and provide correct tag name')
    return False

  return True

def build_image(args):
  """Builds docker image."""
  if args.pull and args.no_pull:
    logger.error('Incompatible arguments --pull and --no-pull.')
    return False
  
  if args.push == True and args.tag == "":
    logger.error('Must provide image name (--tag) on push')
    return False

  if args.pull:
    pull = True
  else:
    pull = False

  if pull:
    logger.info('Pulling latest base images...')
  else:
    logger.info('Using cached base images...')

  # If build_image is called explicitly, don't use cache.
  if build_image_impl(args.project,
                      cache=args.cache,
                      pull=pull,
                      target=args.target,
                      push=args.push,
                      tag=args.tag,
                      architecture=args.architecture):
    return True

  return False


def build_fuzzers_impl(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
    project,
    clean,
    engine,
    sanitizer,
    architecture,
    env_to_add,
    source_path,
    mount_path=None,
    child_dir='',
    build_project_image=True,
    build_image_name=None,
    push_build=False):
  """Builds fuzzers."""
  try:
    source_args = _source_docker_args(project, source_path, mount_path)
  except ValueError as error:
    logger.error('%s', error)
    return False

  if build_image_name is None:
    image_name = f'{project.name}_build_img'
  else:
    image_name = build_image_name

  if build_project_image and not build_image_impl(project,
                                                   architecture=architecture,
                                                   tag=build_image_name):
      return False
    # do not build image but pull latest image
  elif not build_project_image:
    if not docker_pull(build_image_name):
      if not docker_image_exists(build_image_name):
        logger.error('Image %s: pull failed and image not found locally.',
                       build_image_name)
        return False
      logger.info('Pull failed, using existing local image %s.', build_image_name)

  project_out = os.path.join(project.out, child_dir)
    # if sanitizer == "introspector":
    #   # fuzz_introspector needs code coverage report when building
    #   shutil.copytree(os.path.join(project.out, "libfuzzer_coverage", "textcov_reports"), os.path.join(project_out, "textcov_reports"))

  if clean:
    logger.info('Cleaning existing build artifacts.')

    # Clean old and possibly conflicting artifacts in project's out directory.
    docker_run([
        '-v', f'{project_out}:/out', '-t', image_name, '/bin/bash', '-c', 'rm -rf /out/*'
    ], architecture=architecture)

    docker_run([
        '-v', f'{project.work}:/work', '-t', image_name, '/bin/bash', '-c', 'rm -rf /work/*'
    ], architecture=architecture)

  else:
    logger.info('Keeping existing build artifacts as-is (if any).')
  env = [
      'FUZZING_ENGINE=' + engine,
      'SANITIZER=' + sanitizer,
      'ARCHITECTURE=' + architecture,
      'PROJECT_NAME=' + project.name,
      'HELPER=True',
  ]

  _add_oss_fuzz_ci_if_needed(env)

  if project.language:
    env.append('FUZZING_LANGUAGE=' + project.language)

  if env_to_add:
    env += env_to_add

  command = _env_to_docker_args(env) + _mode_docker_args(project, builder=True)
  command += source_args

  command += [
      '-v', f'{project_out}:/out', '-v', f'{project.work}:/work', image_name
  ]
  if sys.stdin.isatty():
    command.insert(-1, '-t')

  result = docker_run(command, architecture=architecture)
  if not result:
    logger.error('Building fuzzers failed.')
    return False

  if push_build:
    return push_artifacts(project, project_out, f'{engine}_{sanitizer}_build')

  return True

def build_fuzzers(args):
  """Builds fuzzers."""
  if args.engine == 'centipede' and args.sanitizer != 'none':
    # Centipede always requires separate binaries for sanitizers:
    # An unsanitized binary, which Centipede requires for fuzzing.
    # A sanitized binary, placed in the child directory.
    sanitized_binary_directories = (
        ('none', ''),
        (args.sanitizer, f'__centipede_{args.sanitizer}'),
    )
  else:
    child_dir = ''
    if args.use_separate_dir == True:
      child_dir = f"{args.engine}_{args.sanitizer}_build"
    # Generally, a fuzzer only needs one sanitized binary in the default dir.
    sanitized_binary_directories = ((args.sanitizer, child_dir),)
  return all(
      build_fuzzers_impl(args.project,
                         args.clean,
                         args.engine,
                         sanitizer,
                         args.architecture,
                         args.e,
                         args.source_path,
                         mount_path=args.mount_path,
                         child_dir=child_dir,
                         build_project_image=args.build_project_image,
                         build_image_name=args.build_image_name,
                         push_build=args.push)
      for sanitizer, child_dir in sanitized_binary_directories)


def _add_oss_fuzz_ci_if_needed(env):
  """Adds value of |OSS_FUZZ_CI| environment variable to |env| if it is set."""
  oss_fuzz_ci = os.getenv('OSS_FUZZ_CI')
  if oss_fuzz_ci:
    env.append('OSS_FUZZ_CI=' + oss_fuzz_ci)

def check_build(args):
  """Checks that fuzzers in the container execute without errors."""
  if not check_project_exists(args.project):
    return False

  if (args.fuzzer_name and not _check_fuzzer_exists(
      args.project, args.fuzzer_name, args.architecture)):
    return False

  env = [
      'FUZZING_ENGINE=' + args.engine,
      'SANITIZER=' + args.sanitizer,
      'ARCHITECTURE=' + args.architecture,
      'FUZZING_LANGUAGE=' + args.project.language,
      'HELPER=True',
  ]
  _add_oss_fuzz_ci_if_needed(env)
  if args.e:
    env += args.e

  run_args = _env_to_docker_args(env) + [
      '-v', f'{args.project.out}:/out', '-t', BASE_RUNNER_IMAGE
  ]

  if args.fuzzer_name:
    run_args += ['test_one.py', args.fuzzer_name]
  else:
    run_args.append('test_all.py')

  result = docker_run(run_args, architecture=args.architecture)
  if result:
    logger.info('Check build passed.')
  else:
    logger.error('Check build failed.')

  return result


def _get_fuzz_targets(project):
  """Returns names of fuzz targest build in the project's /out directory."""
  fuzz_targets = []
  for name in os.listdir(project.out):
    if name.startswith('afl-'):
      continue
    if name == 'centipede':
      continue
    if name.startswith('jazzer_'):
      continue
    if name == 'llvm-symbolizer':
      continue

    path = os.path.join(project.out, name)
    # Python and JVM fuzz targets are only executable for the root user, so
    # we can't use os.access.
    if os.path.isfile(path) and (os.stat(path).st_mode & 0o111):
      fuzz_targets.append(name)

  return fuzz_targets


def _get_artifact_repository_user():
  """Returns username and password from environment variables.
  Now we only support Nexus storage"""

  nexus_user = os.getenv("NEXUS_USER")
  if nexus_user == None:
    logger.error('Can not push/pull artifacts to Nexus repository without Nexus user. '
                 'Set NEXUS_USER environment variable')
    return None, None

  nexus_token = os.getenv("NEXUS_TOKEN")
  if nexus_token == None:
    logger.error('Can not push/pull artifacts to Nexus repository without api token. '
                 'Set NEXUS_TOKEN environment variable')
    return None, None
  
  return nexus_user, nexus_token

def _get_artifacts_archive(project, artifacts_name, target_dir=None):
    """Downloads artifacts from Nexus repository"""
    target_out_dir = project.out
    target_archive_name = artifacts_name + ".tar.gz"
    target_archive_path = os.path.join(target_out_dir, target_archive_name)

    if not _download_archive(project_name=project.name, archive_filename=target_archive_name, output_file=target_archive_path):
        return False

    if target_dir is None:
        target_path = project.out
    else:
        target_path = _get_project_build_subdir(project.path, target_dir)

    try:
        with open(os.devnull, 'w') as stdout:
            subprocess.check_call(
                ['tar', 'xfz', target_archive_path, '-C', target_path],
                stdout=stdout)
    except OSError:
        logger.error('Failed to untar artifacts')
        return False

    os.remove(target_archive_path)
    return True

def download_artifacts(args, artifacts_name="corpus"):
  """Downloads most recent artifacts from repository for the given project."""
  if not check_project_exists(args.project):
    return False

  logger.info("Downloading artifacts")
  try:
    with open(os.devnull, 'w') as stdout:
      subprocess.check_call(['wget', '--version'], stdout=stdout)
  except OSError:
    logger.error('wget not found')
    return False

  if args.fuzz_target:
    fuzz_targets = (args.fuzz_target, )
  else:  
    fuzz_targets = _get_fuzz_targets(args.project)

  if not fuzz_targets:
    logger.error(
        'Fuzz targets not found. Please build project first '
        '(python3 infra/helper.py build_fuzzers %s) so that download_artifacts '
        'can automatically identify targets.', args.project.name)
    return False


  def _download_for_single_target(fuzz_target):
    try:
      _get_artifacts_archive(args.project, f"{fuzz_target}_{artifacts_name}", f"{artifacts_name}/{fuzz_target}")
      return True
    except Exception as error:  # pylint:disable=broad-except
      logger.error('Corpus download for %s failed: %s.', fuzz_target, str(error))
      return False

  logger.info('Downloading corpora for %s.', args.project.name)
  thread_pool = ThreadPool()
  return all(thread_pool.map(_download_for_single_target, fuzz_targets))

def pull_build_artifacts(project, artifacts_dir):
  user, password = _get_artifact_repository_user()
  if user == None or password==None:
    return False

  try:
    _get_artifacts_archive(project, artifacts_dir)
    return True
  except Exception as error:  # pylint:disable=broad-except
    logger.error('Build artifacts download for %s failed: %s.', artifacts_dir, str(error))
    return False

def push_artifacts(project, artifacts_dir, artifacts_name=""):
    if not os.path.exists(artifacts_dir):
        logger.warning("Artifacts directory doesn't exist, can not push artifacts")
        return False

    artifacts_archive = os.path.basename(os.path.normpath(artifacts_dir)) + ".tar.gz"
    if artifacts_name:
        artifacts_archive = artifacts_name + ".tar.gz"

    logger.info(f"Creating archive with artifacts {artifacts_archive}")
    try:
        with open(os.devnull, 'w') as stdout:
            subprocess.check_call(
                ['tar', 'cfz', artifacts_archive, '-C', artifacts_dir, '.'],
                stdout=stdout)
    except OSError:
        logger.error('Failed to create tar archive')
        return False

    archive_path = os.path.join(os.getcwd(), artifacts_archive)

    logger.info("Uploading archive to repository")
    if not _upload_archive(project.name, archive_path, artifacts_archive):
        # Не забываем подчистить локальный архив даже при ошибке
        _remove_quiet(artifacts_archive)
        return False

    logger.info("Removing the local archive with artifacts")
    _remove_quiet(artifacts_archive)

    return True

def _remove_quiet(path):
    try:
        with open(os.devnull, 'w') as stdout:
            subprocess.check_call(['rm', '-f', path], stdout=stdout)
    except OSError:
        logger.error('Failed to remove %s', path)

def merge_coverage_reports(project):
    """
    Merge coverage reports from report_target/<target_name>/linux/ into a
    global coverage report in coverage/.
    Returns True on success.
    """
    coverage_dir = os.path.join(project.out, "coverage")
    os.makedirs(coverage_dir, exist_ok=True)

    # 1. Download previous merged report if exists
    if _get_artifacts_archive(project, "coverage", "out/coverage"):
        logger.info("Previous coverage report downloaded successfully.")
    else:
        logger.info("No previous coverage report found. Creating new one.")
        # Create an initial index.html if not present
        index_path = os.path.join(coverage_dir, "index.html")
        if not os.path.exists(index_path):
            with open(index_path, "w") as f:
                f.write("<html><head><title>Coverage Reports</title></head><body><h1>Coverage Reports</h1><ul></ul></body></html>")

    # Copy global style.css if available from any report (e.g., from the first target)
    # First, try to find a style.css in any report_target subdir
    src_css = None
    report_target_root = os.path.join(project.out, "report_target")
    if os.path.isdir(report_target_root):
        for target_name in os.listdir(report_target_root):
            candidate = os.path.join(report_target_root, target_name, "linux", "style.css")
            if os.path.exists(candidate):
                src_css = candidate
                break

    if not src_css:
        # fallback to old location
        fallback_css = os.path.join(project.out, "report", "style.css")
        if os.path.exists(fallback_css):
            src_css = fallback_css

    if src_css:
        dst_css = os.path.join(coverage_dir, "style.css")
        shutil.copy2(src_css, dst_css)
        logger.info("Copied style.css to %s", dst_css)
    else:
        logger.debug("No style.css found.")

    # 2. Iterate over each target in report_target and copy its report
    if not os.path.isdir(report_target_root):
        logger.error("report_target directory not found: %s", report_target_root)
        return False

    target_folders = [d for d in os.listdir(report_target_root)
                      if os.path.isdir(os.path.join(report_target_root, d))]
    if not target_folders:
        logger.warning("No target reports found in %s", report_target_root)
        return False

    for target_name in target_folders:
        src_report_dir = os.path.join(report_target_root, target_name, "linux")
        if not os.path.isdir(src_report_dir):
            logger.debug("No linux subdir for target %s, skipping", target_name)
            continue
        dst_report_dir = os.path.join(coverage_dir, target_name)
        # Remove old report for this target if exists
        if os.path.exists(dst_report_dir):
            shutil.rmtree(dst_report_dir)
        shutil.copytree(src_report_dir, dst_report_dir)
        logger.info("Copied report for %s to %s", target_name, dst_report_dir)

    # 3. Update index.html based on all existing subdirectories in coverage_dir
    subdirs = []
    for item in os.listdir(coverage_dir):
        item_path = os.path.join(coverage_dir, item)
        if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "index.html")):
            subdirs.append(item)

    html_content = """<html>
<head><title>OSS-Fuzz Coverage Reports</title></head>
<body>
<h1>Coverage Reports by Fuzz Target</h1>
<ul>
"""
    for sub in sorted(subdirs):
        html_content += f'<li><a href="{sub}/index.html">{sub}</a></li>\n'
    html_content += """</ul>
</body>
</html>"""

    with open(os.path.join(coverage_dir, "index.html"), "w") as f:
        f.write(html_content)

    logger.info("Updated index.html with %d reports", len(subdirs))
    return True

def coverage(args):  # pylint: disable=too-many-branches
  """Generates code coverage using clang source based code coverage."""
  if args.corpus_dir and not args.fuzz_target:
    logger.error(
        '--corpus-dir requires specifying a particular fuzz target using '
        '--fuzz-target')
    return False

  project = args.project
  if not check_project_exists(project):
    return False

  if project.language not in constants.LANGUAGES_WITH_COVERAGE_SUPPORT:
    logger.error(
        'Project is written in %s, coverage for it is not supported yet.',
        project.language)
    return False

  if (not args.no_corpus_download and not args.corpus_dir):
    if not download_artifacts(args):
      return False
  
  if args.pull_build:
    if not pull_build_artifacts(project, "libfuzzer_coverage_build"):
      return False

  if args.engine:
    engine = args.engine
  elif project.fuzzing_engine:
    engine = project.fuzzing_engine
  else:
    engine = "libfuzzer"

  extra_cov_args = (
      f'{project.coverage_extra_args.strip()} {" ".join(args.extra_args)}')
  env = [
      'FUZZING_ENGINE=' + engine,
      'HELPER=True',
      'FUZZING_LANGUAGE=%s' % project.language,
      'PROJECT=%s' % project.name,
      'SANITIZER=coverage',
      'COVERAGE_EXTRA_ARGS=%s' % extra_cov_args,
      'ARCHITECTURE=' + args.architecture,
  ]

  run_args = _env_to_docker_args(env) + _mode_docker_args(project)

  if engine == "sydr-fuzz":
    sydr_out = _get_project_build_subdir(project.out, args.fuzz_target + "_out")
    
    if not os.path.exists(sydr_out):
      logger.warning("Can not find sydr-fuzz output directory")
    elif not args.corpus_dir or not os.path.exists(args.corpus_dir):
      args.corpus_dir = os.path.join(sydr_out, "corpus")

  if args.corpus_dir:
    if not os.path.exists(args.corpus_dir):
      logger.error('The path provided in --corpus-dir argument does not '
                   'exist.')
      return False
    corpus_dir = os.path.realpath(args.corpus_dir)
    run_args.extend(['-v', '%s:/corpus/%s' % (corpus_dir, args.fuzz_target)])
  else:
    run_args.extend(['-v', '%s:/corpus' % project.corpus])

  if args.run_img:
    run_image = args.run_img
  else:
    run_image = BASE_RUNNER_IMAGE

  run_args.extend([
      '-v',
      '%s:/out' % project.out,
      '-t',
      run_image,
  ])

  run_args.append('coverage')
  if args.fuzz_target:
    run_args.append(args.fuzz_target)

  result = docker_run(run_args, architecture=args.architecture)
  if result:
    logger.info('Successfully generated code coverage report.')
  else:
    logger.error('Failed to generate code coverage report.')
    return False
  
  if args.push_artifacts:
    if merge_coverage_reports(project):
        cov_report_dir = os.path.join(args.project.out, "coverage")
        if args.artifacts_tag:
          push_artifacts(args.project, cov_report_dir, artifacts_name=f"coverage_{args.artifacts_tag}")
        return push_artifacts(args.project, cov_report_dir, artifacts_name="coverage")
    else:
        logger.error("Failed to merge coverage report.")
        return False

  return result

def _casr_target(args, project, engine, sanitizer, use_sydr, fuzz_target):
  if use_sydr:
    if not args.no_crashes_download:
      if not _get_artifacts_archive(project, f"{fuzz_target}_out",
                                    f"out/{fuzz_target}_out"):
        logger.warning('No fuzzing output downloaded for %s, skipping.',
                       fuzz_target)
        return True

    crash_dir = args.crash_dir
    sydr_out = _get_project_build_subdir(project.out, fuzz_target + "_out")
    if not crash_dir or not os.path.exists(crash_dir):
      if not os.path.exists(sydr_out):
        logger.warning(f'--crash_dir is not set and the default sydr-fuzz output directory {sydr_out} does not exist.')
        return False
      crash_dir = _get_project_build_subdir(sydr_out, "crashes")
  else:
    crash_dir = args.crash_dir
    if not crash_dir and not args.no_crashes_download:
      if not _get_artifacts_archive(project, f"{fuzz_target}_crashes",
                                    f"crashes/{fuzz_target}"):
        logger.warning('No crashes downloaded for %s, skipping.', fuzz_target)
        return True
      crash_dir = os.path.join(project.path, "crashes", fuzz_target)

  if not crash_dir or not os.path.exists(crash_dir) or not os.listdir(crash_dir):
    logger.info('No crashes found for %s, skipping.', fuzz_target)
    return True

  fuzzer_out = f'/out/{fuzz_target}_out'
  casr_out_dir = '/out/casr_out'

  env = [
      'FUZZING_ENGINE=' + engine,
      'SANITIZER=' + sanitizer,
      'HELPER=True',
      'FUZZING_LANGUAGE=%s' % project.language,
      'PROJECT=%s' % project.name,
      'FUZZER_OUT=' + fuzzer_out,
      'CASR_OUT_DIR=' + casr_out_dir,
      'CRASHES_DIR=/tmp/crashes/'
  ]

  if args.dojo_url:
    dd_token = os.getenv("DD_TOKEN")
    if dd_token == None:
      logger.error('Can not push crashes to DefectDojo without DD_TOKEN. '
                   'Set DD_TOKEN environment variable')
      return False

    env.append('DD_URL=' + args.dojo_url)
    env.append('DD_TOKEN=' + dd_token)

    dojo_product = args.dojo_product
    if not dojo_product:
      dojo_product = project.name
    env.append('DD_PRODUCT=' + dojo_product)

    dojo_engagement = args.dojo_engagement
    if not dojo_engagement:
      dojo_engagement = fuzz_target
    env.append('DD_ENGAGEMENT=' + dojo_product)

  run_args = _env_to_docker_args(env) + _mode_docker_args(project)

  if use_sydr:
    sydr_path = os.getenv("SYDR_PATH")
    if not sydr_path or not os.path.isdir(sydr_path):
      logger.error('Can not use sydr-fuzz without a valid SYDR_PATH directory. '
                   'Set SYDR_PATH or select another engine via --engine.')
      return False

    run_args.extend(['-v', f'{sydr_path}:/sydr', '--network', 'host', '-v', '/var/hasplm:/var/hasplm', '-v', '/etc/hasplm:/etc/hasplm'])
    
  crash_dir = os.path.realpath(crash_dir)
  run_args.extend(['-v', '%s:/tmp/crashes/' % (crash_dir)])

  run_args.extend(['-v', f'{project.out}:/out'])

  if args.run_img:
    run_image = args.run_img
  else:
    run_image = BASE_RUNNER_IMAGE

  run_args.extend([
      '--cap-add=SYS_PTRACE',
      '--security-opt',
      'seccomp=unconfined',
      '-v',
      f'{project.casr_out}:{casr_out_dir}',
      '-v',
      f'{project.fuzzing_out(fuzz_target)}:{fuzzer_out}',
      run_image,
      'casr',
      fuzz_target,
  ])

  if not docker_run(run_args):
    logger.error('Failed to triage crashes for %s with casr.', fuzz_target)
    return False

  if args.push_artifacts:
    if use_sydr and project.language not in ("jvm", "python", "javascript"):
      report_dir = os.path.join(project.fuzzing_out(fuzz_target), "casr")
    else:
      report_dir = os.path.join(project.casr_out, fuzz_target)
    if not os.path.exists(report_dir):
      logger.info('No casr report produced for %s, nothing to push.',
                  fuzz_target)
      return True
    return push_artifacts(project, report_dir, artifacts_name=f"{fuzz_target}_casr")

  return True

def casr(args):  # pylint: disable=too-many-branches
  """Triages crashes found during fuzzing with CASR."""
  project = args.project
  if not check_project_exists(project):
    return False

  if project.language not in constants.LANGUAGES_WITH_CASR_SUPPORT:
    logger.error(
        'Project is written in %s, casr for it is not supported yet.',
        project.language)
    return False

  if args.engine:
    engine = args.engine
  elif project.fuzzing_engine:
    engine = project.fuzzing_engine
  else:
    engine = "libfuzzer"

  sanitizer = args.sanitizer if args.sanitizer else constants.DEFAULT_SANITIZER

  use_sydr = engine == "sydr-fuzz"

  if args.pull_build:
    if not pull_build_artifacts(project, f"{engine}_{sanitizer}_build"):
      return False

  if args.fuzz_target:
    fuzz_targets = [args.fuzz_target]
  else:
    fuzz_targets = _get_fuzz_targets(project)

  if not fuzz_targets:
    logger.error(
        'Fuzz targets not found. Please build project first '
        '(python3 infra/helper.py build_fuzzers %s) so that casr '
        'can automatically identify targets.', project.name)
    return False

  result = True
  for fuzz_target in fuzz_targets:
    if not _casr_target(args, project, engine, sanitizer, use_sydr, fuzz_target):
      result = False

  if result:
    logger.info('Successfully triaged crash reports with casr.')
  else:
    logger.error('Failed to triage crash reports with casr.')

  return result

# def run_pipeline_scheduler(args):
#   """function to get all projects for a group with a ready pipeline"""
#   private_token = args.private_token

#   if private_token == None:
#     private_token = os.environ.get('GITLAB_FUZZ_TOKEN', '')

#   scheduler = pipeline_scheduler.FuzzingPipelineScheduler(
#         gitlab_url=args.gitlab_url,
#         private_token=private_token,
#         group_id=args.group_id
#     )

#   # Запуск планировщика
#   scheduler.schedule_pipelines()

def _introspector_prepare_corpus(args):
  """Helper function for introspector runs to generate corpora."""
  parser = get_parser()
  # Generate corpus, either by downloading or running fuzzers.
  if args.private_corpora or args.public_corpora:
    corpora_command = ['download_artifacts']
    corpora_command.append(args.project.path)
    if not download_artifacts(parse_args(parser, corpora_command)):
      logger.error('Failed to download corpora')
      return False
  else:
    fuzzer_targets = _get_fuzz_targets(args.project)
    for fuzzer_name in fuzzer_targets:
      # Make a corpus directory.
      fuzzer_corpus_dir = args.project.corpus + f'/{fuzzer_name}'
      if not os.path.isdir(fuzzer_corpus_dir):
        os.makedirs(fuzzer_corpus_dir)
      run_fuzzer_command = [
          'run_fuzzer', '--sanitizer', 'address', '--corpus-dir',
          fuzzer_corpus_dir, args.project.name, fuzzer_name
      ]

      parsed_args = parse_args(parser, run_fuzzer_command)
      parsed_args.fuzzer_args = [
          f'-max_total_time={args.seconds}', '-detect_leaks=0'
      ]
      # Continue even if run command fails, because we do not have 100%
      # accuracy in fuzz target detection, i.e. we might try to run something
      # that is not a target.
      run_fuzzer(parsed_args)
  return True


def introspector(args):
  """Runs a complete end-to-end run of introspector."""
  parser = get_parser()

  args_to_append = []
  if args.source_path:
    args_to_append.append(_get_absolute_path(args.source_path))

  # Build fuzzers with ASAN.
  build_fuzzers_command = [
      'build_fuzzers', '--sanitizer=address', args.project.path
  ] + args_to_append
  if not build_fuzzers(parse_args(parser, build_fuzzers_command)):
    logger.error('Failed to build project with ASAN')
    return False

  if not _introspector_prepare_corpus(args):
    return False

  # Build code coverage.
  build_fuzzers_command = [
      'build_fuzzers', '--sanitizer=coverage', args.project.path
  ] + args_to_append
  if not build_fuzzers(parse_args(parser, build_fuzzers_command)):
    logger.error('Failed to build project with coverage instrumentation')
    return False

  # Collect coverage.
  coverage_command = [
      'coverage', args.project.path
  ]

  if args.push_artifacts:
    coverage_command.insert(1, "--push_artifacts")

  if not coverage(parse_args(parser, coverage_command)):
    logger.error('Failed to extract coverage')
    return False
  
  # Build introspector.
  build_fuzzers_command = [
      'build_fuzzers', '--sanitizer=introspector', args.project.path
  ] + args_to_append
  if not build_fuzzers(parse_args(parser, build_fuzzers_command)):
    logger.error('Failed to build project with introspector')
    return False

  introspector_dst = os.path.join(args.project.out,
                                  "introspector-report/inspector")
  shutil.rmtree(introspector_dst, ignore_errors=True)
  shutil.copytree(os.path.join(args.project.out, "inspector"), introspector_dst)

  # Copy the coverage reports into the introspector report.
  dst_cov_report = os.path.join(introspector_dst, "covreport")
  shutil.copytree(os.path.join(args.project.out, "report"), dst_cov_report)

  # Copy per-target coverage reports
  src_target_cov_report = os.path.join(args.project.out, "report_target")
  for target_cov_dir in os.listdir(src_target_cov_report):
    dst_target_cov_report = os.path.join(dst_cov_report, target_cov_dir)
    shutil.copytree(os.path.join(src_target_cov_report, target_cov_dir),
                    dst_target_cov_report)

  logger.info('Introspector run complete. Report in %s', introspector_dst)
  logger.info(
      'To browse the report, run: `python3 -m http.server 8008 --directory %s`'
      'and navigate to localhost:8008/fuzz_report.html in your browser',
      introspector_dst)
  if (args.push_artifacts):
    return push_artifacts(args.project, introspector_dst, artifacts_name="introspector")
  return True


def run_fuzzer(args):
  """Runs a fuzzer in the container."""
  if not check_project_exists(args.project):
    return False

  # TODO add support for checking fuzzers
  # if not _check_fuzzer_exists(args.project, args.fuzzer_name,
  #                             args.architecture):
  #   return False

  project = args.project
  if project.fuzzing_engine:
    engine = project.fuzzing_engine
  elif args.engine != None:
    engine = args.engine
  else:
    logging.error('fuzzing_engine unspecified')
    return False

  binary_path = project.out

  if args.pull_build:
    if not pull_build_artifacts(project, engine + "_" + args.sanitizer + "_build"):
      return False

  artifacts_dir_name = f"{args.fuzzer_name}_out"

  artifacts_dir_path = _get_project_build_subdir(project.out, artifacts_dir_name)
  fuzzer_out = f'/out/{artifacts_dir_name}'

  if args.pull_artifacts:
    try:
      _get_artifacts_archive(project, artifacts_dir_name, artifacts_dir_path)
    except Exception as error:  # pylint:disable=broad-except
      logger.error('Fuzzing artifacts download for %s failed: %s.', artifacts_dir_name, str(error))
      return False

  env = [
      'FUZZING_ENGINE=' + engine,
      'SANITIZER=' + (args.sanitizer if args.sanitizer else ''),
      'RUN_FUZZER_MODE=interactive',
      'HELPER=True',
      'FUZZER_OUT=' + fuzzer_out,
      'CMIN=' + str(not args.no_cmin),
      'CLEAN=' + str(args.clean),
      'WORKERS_NUM=' + str(args.workers),
  ]

  timeout = args.timeout
  if timeout:
    env.append('TIMEOUT=' + timeout)

  if args.e:
    env += args.e

  run_args = _env_to_docker_args(env) + _mode_docker_args(project)

  if engine == "sydr-fuzz":
    # mount sydr-fuzz to $OUT/sydr-fuzz
    sydr_path = os.getenv("SYDR_PATH")
    if sydr_path == None:
      logger.error('Can not use sydr-fuzz without SYDR_PATH env')
      return False

    if not os.path.isdir(sydr_path):
      logger.error("SYDR_PATH doesn't seem to exist or not a directory."
                   "Check that SYDR_PATH points to the valid directory with sydr-fuzz binary")

    # add flags for sydr-fuzz
    run_args.extend(['-v', f'{sydr_path}:/sydr', '--network', 'host', '-v', '/var/hasplm:/var/hasplm', '-v', '/etc/hasplm:/etc/hasplm'])

    # sydr-fuzz needs all builds in the same container
    # mounts all build dirs in out
    run_args.extend(['-v', f'{project.out}:/out'])
  else:
    run_args.extend(['-v', f'{binary_path}:/out'])

  # Mount corpus and crashes directories
  run_args.extend(['-v', '%s:/corpus' % project.corpus])
  run_args.extend(['-v', '%s:/crashes' % project.crashes])

  if args.corpus_dir:
    if not os.path.exists(args.corpus_dir):
      logger.error('The path provided in --corpus-dir argument does not exist')
      return False
    corpus_dir = os.path.realpath(args.corpus_dir)
    run_args.extend([
        '-v',
        '{corpus_dir}:/tmp/{fuzzer}_corpus'.format(corpus_dir=corpus_dir,
                                                   fuzzer=args.fuzzer_name)
    ])

  if args.run_img:
    run_image = args.run_img
  else:
    run_image = _get_base_runner_image(args)

  run_args.extend([
      '-t',
      run_image,
      'run_fuzzer',
      args.fuzzer_name,
  ] + args.fuzzer_args)

  if not docker_run(run_args, architecture=args.architecture):
    return False

  if args.push_artifacts:
    push_artifacts(project, artifacts_dir_path)
    if args.artifacts_tag:
      push_artifacts(project, artifacts_dir_path, f"{artifacts_dir_name}_{args.artifacts_tag}")
    if engine == "sydr-fuzz":
      for artifact in ("corpus", "crashes"):
        artifact_dir = _get_project_build_subdir(artifacts_dir_path, artifact)
        push_artifacts(project, artifact_dir, f"{args.fuzzer_name}_{artifact}")

  return True

def reproduce(args):
  """Reproduces a specific test case from a specific project."""
  return reproduce_impl(args.project, args.fuzzer_name, args.valgrind, args.e,
                        args.fuzzer_args, args.testcase_path, args.architecture)


def reproduce_impl(  # pylint: disable=too-many-arguments
    project,
    fuzzer_name,
    valgrind,
    env_to_add,
    fuzzer_args,
    testcase_path,
    architecture='x86_64',
    run_function=docker_run,
    err_result=False):
  """Reproduces a testcase in the container."""
  if not check_project_exists(project):
    return err_result

  if not _check_fuzzer_exists(project, fuzzer_name, architecture):
    return err_result

  debugger = ''
  env = ['HELPER=True', 'ARCHITECTURE=' + architecture]
  image_name = 'base-runner'

  if valgrind:
    debugger = 'valgrind --tool=memcheck --track-origins=yes --leak-check=full'

  if debugger:
    image_name = 'base-runner-debug'
    env += ['DEBUGGER=' + debugger]

  if env_to_add:
    env += env_to_add

  run_args = _env_to_docker_args(env) + [
      '-v',
      '%s:/out' % project.out,
      '-v',
      '%s:/testcase' % _get_absolute_path(testcase_path),
      '-t',
      'gcr.io/oss-fuzz-base/%s' % image_name,
      'reproduce',
      fuzzer_name,
      '-runs=100',
  ] + fuzzer_args

  return run_function(run_args, architecture=architecture)


def _validate_project_name(project_name):
  """Validates |project_name| is a valid OSS-Fuzz project name."""
  if len(project_name) > MAX_PROJECT_NAME_LENGTH:
    logger.error(
        'Project name needs to be less than or equal to %d characters.',
        MAX_PROJECT_NAME_LENGTH)
    return False

  if not VALID_PROJECT_NAME_REGEX.match(project_name):
    logger.info('Invalid project name: %s.', project_name)
    return False

  return True


def shell(args):
  """Runs a shell within a docker image."""

  try:
    source_args = _source_docker_args(args.project, args.source_path)
  except ValueError as error:
    logger.error('%s', error)
    return False

  env = [
      'FUZZING_ENGINE=' + args.engine,
      'SANITIZER=' + args.sanitizer,
      'ARCHITECTURE=' + args.architecture,
      'HELPER=True',
  ]

  if args.project.name != 'base-runner-debug':
    env.append('FUZZING_LANGUAGE=' + args.project.language)

  if args.e:
    env += args.e

  if getattr(args, 'build_image_name', None):
    if not docker_image_exists(args.build_image_name):
      logger.error('Image %s not found locally. Build or pull it first.', args.build_image_name)
      return False
    image_name = args.build_image_name
  else:
    if not build_image_impl(args.project):
      return False
    image_name = f'{args.project.name}_build_img'
  out_dir = args.project.out

  run_args = _env_to_docker_args(env) + _mode_docker_args(args.project, builder=True)
  run_args += source_args

  run_args.extend([
      '--entrypoint', '',
      '-v',
      '%s:/out' % out_dir, '-v',
      '%s:/work' % args.project.work, '-t',

      image_name, '/bin/bash'
  ])

  return docker_run(run_args, architecture=args.architecture)


def pull_images(language=None):
  """Pulls base images used to build projects in language lang (or all if lang
  is None)."""
  for base_image_lang, base_images in BASE_IMAGES.items():
    if (language is None or base_image_lang == 'generic' or
        base_image_lang == language):
      for base_image in base_images:
        if not docker_pull(base_image):
          return False

  return True


if __name__ == '__main__':
  sys.exit(main())
