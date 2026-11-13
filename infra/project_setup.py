# Copyright 2026 Fobos-NT.
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

"""Development project initialization and target scaffolding."""

import logging
import os
import re
import subprocess
from types import SimpleNamespace

import templates

logger = logging.getLogger(__name__)
NAME_RE = re.compile(r'[a-zA-Z0-9_.-]+')


def _write(path, content, force=False, executable=False):
  """Preserve existing files unless the user explicitly requested --force."""
  if os.path.lexists(path) and not force:
    logger.info('Keeping existing %s', path)
    return False
  with open(path, 'w') as handle:
    handle.write(content)
  if executable:
    os.chmod(path, 0o755)
  logger.info('Created %s', path)
  return True

def generate(args):
  """Create the project repository and templates."""
  project = args.project

  try:
    if not NAME_RE.fullmatch(project.name):
      raise ValueError('Invalid project name: %s' % project.name)
    if args.target and not NAME_RE.fullmatch(args.target):
      raise ValueError('Invalid target name: use letters, digits, _ and -')
    os.makedirs(project.path, exist_ok=True)

    directory = project.build_integration_path
    for name in ('assets', 'sources', 'out', 'work'):
      os.makedirs(os.path.join(project.path, name), exist_ok=True)

    if args.language in ('c', 'c++'):
        introspector_block = templates.INTROSPECTOR_BLOCK
        sydr_build_block = templates.SYDR_C_BUILD_BLOCK
    else:
        introspector_block = ''
        sydr_build_block = templates.SYDR_NO_C_BUILD_BLOCK

    substitutions = {
        'project_name': project.name,
        'base_builder': templates.LANGUAGE_TO_BASE_BUILDER_IMAGE[args.language],
        'language': args.language,
        'target': args.target or 'my_target',
        'fuzz_ext': templates.HARNESS_EXTENSIONS[args.language],
        'introspector_block': introspector_block,
        'sydr_build_block': sydr_build_block,
    }

    for name, template in templates.TEMPLATES.items():
      content = template % substitutions
      _write(os.path.join(directory, name), content, args.force, name.endswith('.sh'))

    if args.target:
      if not add_target(SimpleNamespace(project=project, name=args.target, force=args.force, language=args.language)):
        return False
    logger.info('Initialized %s; add wrappers with add_target and fill in build.sh', project.path)
    return True
  except (ValueError, OSError, subprocess.CalledProcessError) as error:
    logger.error('Initialization failed: %s', error)
    return False

def _template_project_file(filename, template, template_args, directory):
  """Templates |template| using |template_args| and writes the result to
  |directory|/|filename|. Sets the file to executable if |filename| is
  build.sh."""
  file_path = os.path.join(directory, filename)
  with open(file_path, 'w') as file_handle:
    file_handle.write(template % template_args)

  if filename == 'build.sh':
    os.chmod(file_path, 0o755)


def add_target(args):
  """Create target files and register the target in README."""
  project, target_name = args.project, args.name
  language = project.language

  try:
    if not NAME_RE.fullmatch(target_name):
      raise ValueError('Invalid target name: use letters, digits, _ and -')

    target_asset_dir = os.path.join(project.path, "assets", target_name)
    try:
      os.makedirs(target_asset_dir, exist_ok=True)
    except OSError as error:
      logger.info('%s can not create directory: %s', target_asset_dir, error)
      return False

    fuzz_target_ext = templates.HARNESS_EXTENSIONS[language]
    _template_project_file(
        f"{target_name}_fuzz.{fuzz_target_ext}",
        "",
        [],
        target_asset_dir
    )

    _template_project_file(
        f"{target_name}.dict",
        "# Dictionary file\\n",
        [],
        target_asset_dir
    )

    corpus_dir = os.path.join(target_asset_dir, f"{target_name}_seed_corpus")
    os.makedirs(corpus_dir, exist_ok=True)

    logger.info('Added %s; implement the wrapper and build_target() in build.sh', target_name)
    return True
  except (ValueError, OSError) as error:
    logger.error('Adding target failed: %s', error)
    return False
