import sys
from pathlib import Path
sys.path.insert(0, str(Path('packages/shared_core').resolve()))
try:
    from nazokake_core import env_config
    print('Path: ' + str(env_config.env_file))
    print('Exists: ' + str(env_config.env_file.exists()))
    if env_config.api_key:
        print('Key Loaded. Length: ' + str(len(env_config.api_key)))
    else:
        print('Key Missing')
except Exception as e:
    print(str(e))
