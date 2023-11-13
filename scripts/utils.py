import os
import pathlib
import re
from typing import List, Dict
import yaml

REPO = pathlib.Path(__file__).parents[1]


def ymlPart(file: pathlib.Path) -> str:
    with open(file, 'r', encoding='utf8') as f:
        lines = f.read()
        lines = [line for line in
                 re.split(r'---.*\n', lines, re.MULTILINE) if len(line) > 0]
        return lines[0]


def is_ascii(s):
    return all(ord(char) < 128 for char in s)


def usergroups() -> Dict[str, List[dict]]:
    USERS = dict()
    for aname, avalues in authors().items():

        for g in avalues['user_groups']:
            group_users = USERS.get(g, dict())
            if aname not in group_users:
                group_users[aname] = avalues
            USERS[g] = group_users

    return USERS


def authors() -> dict:
    AUTHORS: Dict[str, dict] = dict()
    for d in os.scandir(REPO / 'content' / 'authors'):
        if d.is_dir():

            aname = d.name
            # assert '_' not in aname
            assert ' ' not in aname
            assert is_ascii(aname), f'Folder name needs to be ASCII only: {aname}'

            for n in ['index.md', '_index.md']:
                path_md = pathlib.Path(d.path) / n

                if path_md.is_file():
                    yml = ymlPart(path_md)
                    data = yaml.load(yml, yaml.CLoader)
                    if isinstance(data, dict):
                        authors = data['authors']
                        if aname not in authors:
                            s = ""
                        assert aname in authors, f' {aname} not in {authors}: {path_md}'
                        AUTHORS[aname] = data
    return AUTHORS


if __name__ == "__main__":
    for group, users in usergroups().items():
        print(f'Group: {group}')
        for user in users:
            print(f'\t{user}')
