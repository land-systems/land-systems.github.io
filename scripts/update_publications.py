# A script to update the publications in /content/publication
import argparse
import copy
import datetime
import html
import os
import pathlib
import re
import sys
import typing
import urllib.request
from html.parser import HTMLParser
from typing import Union, List, Tuple
import urllib.parse

import pybtex
import pybtex.database
import pybtex.errors
from academic.editFM import EditableFM
from academic.import_bibtex import clean_bibtex_str, clean_bibtex_tags
from academic.publication_type import PublicationType, PUB_TYPES
from doi2bib.crossref import get_bib_from_doi
from pybtex.database import Person, BibliographyData, Entry

from utils import authors

# pip install pybtext pybtexris
REPLACE = {
    r'{Biodivers. Ecol.}amp$\mathsemicolon$ Ecology}':
        '{Biodiversity & Ecology}'
}

# ['%Y-%b', '%Y-%b %d', '%Y-%b-%d', '%Y-%m-%d', '%Y/%m/%d']
DATE_PATTERNS: List[Tuple[typing.Pattern, str]] = [
    (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),  # ISO date format
    (r'\d{4}/\d{2}/\d{2}', '%Y/%m/%d'),  # Another date format
    (r'\d{4}/\d{2}', '%Y/%m'),
    (r'\d{4}/\d{2}//', '%Y/%m'),
    (r'\d{2}//', '%m//'),
    (r'\d{2}/\d{2}/', '%m/%d/'),
    (r'\d{2}/\d{2}/\d{4}', '%d/%m/%Y'),  # Different date format
    (r'\d{4} \w+ \d{2}', '%Y %b %d'),  # Year, abbreviated month, day
    (r'\d{4} \w+', '%Y %b'),  # Year, abbreviated month
]

DATE_PATTERNS = [(re.compile(r), p) for r, p in DATE_PATTERNS]

root = pathlib.Path(__file__).parents[1]
DIR_PUBLICATION = root / 'content' / 'publication'

url_ris = r'https://box.hu-berlin.de/d/ed4837370b904147a98f/files'
file_url = r'https://box.hu-berlin.de/f/944d10e767e542c7ba72/?dl=1'
tmp_dir = root / 'tmp'

AUTHORS = authors()


# short names
def findContentAuthor(p: Person) -> str:
    """
    Tries to match the Person with an author described in content/authors
    If match is positive, returns the author-name (from content/authors/author-name)
    If match is negative, returns the string with "First Second ... LastName"
    """
    name = ' '.join(p.first_names + p.last_names)

    verylastname = p.last_names[-1].lower()
    if len(p.first_names) > 0:
        firstnameChar1 = p.first_names[0][0].lower()
    else:
        firstnameChar1 = None

    c1 = name.replace(' ', '-').lower()
    c2 = name.replace(' ', '_').lower()
    for k, data in AUTHORS.items():
        authorid = data['authors'][0]
        if k in [c1, c2]:
            return authorid
        if firstnameChar1 and k.endswith(verylastname) and k.startswith(firstnameChar1):
            print(f'Assumed match: {p} == {k}', file=sys.stderr)
            return authorid
    return name


# download, if not existent
class MyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ris_links = []

    def handle_starttag(self, tag, attrs):

        if tag == 'a':
            for attr in attrs:
                if attr[0] == 'href' and attr[1].endswith('.ris'):
                    self.ris_links.append(attr[1])


def cleanBibTexString(text: str) -> str:
    text = clean_bibtex_str(text)
    text = text.replace(r'\"', '"')
    return text


def downloadReferences(enforce: bool = False) -> pathlib.Path:
    """
  Downloads the latest reference from HU-Box ad *.bib file
  :return:
  """
    # Create the download directory if it doesn't exist
    os.makedirs(tmp_dir, exist_ok=True)
    pathSrc = re.split('(&|%2F)', file_url)[-3]
    pathSrc = pathlib.Path(tmp_dir) / pathSrc

    # Check if the file already exists
    if enforce or not os.path.exists(pathSrc):
        print(f"Downloading {pathSrc}...")
        urllib.request.urlretrieve(file_url, pathSrc)
        print(f"{pathSrc} downloaded successfully.")

    assert pathSrc.is_file()

    return pathSrc


def filterByPerson(entries: List[Entry],
                   persons: Union[str, List[str]],
                   first_only: bool = True) -> List[Entry]:
    if isinstance(persons, str):
        persons = [persons]

    persons = [p.lower() for p in persons]

    results = []
    for e in entries:
        epersions = e.persons['author']
        if first_only:
            epersions = epersions[0:1]
        for p in epersions:
            p: Person
            names = [n.lower() for n in p.first_names + p.middle_names + p.last_names]
            if len(set(names).intersection(persons)) > 0:
                results.append(e)
                break

    return results


def checkDOI(db):
    if isinstance(db, str):
        db = pathlib.Path(db)
    if isinstance(db, pathlib.Path):
        db = pybtex.database.parse_file(db)

    assert isinstance(db, BibliographyData)

    db2 = BibliographyData()
    for e in db.entries.values():

        doi = e.fields.get('doi', None)
        if doi:
            print(f'update {doi}...')
            success, bib2 = get_bib_from_doi(doi, add_abstract=True)
            if success:
                e2 = pybtex.database.Entry.from_string(bib2, 'bibtex')
                e2.key = e.key
                db2.add_entry(e2.key, e2)
            else:
                print(f'failed to update {doi}', file=sys.stderr)
                db2.add_entry(e.key, e)
        else:
            print(f'missing doi for: {e}', file=sys.stderr)
            db2.add_entry(e.key, e)

    return db2


def write_publication(DIR_ENTRY: pathlib.Path, e: pybtex.database.Entry, dry_run: bool = False) -> bool:
    """

    :param DIR_ENTRY:
    :param e:
    :return:
    """
    path_md = DIR_ENTRY / 'index.md'
    path_bib = DIR_ENTRY / 'cite.bib'

    if not dry_run:
        os.makedirs(DIR_ENTRY, exist_ok=True)

        with open(path_bib, 'w', encoding='utf8') as f:
            f.write(e.to_string('bibtex'))

    page = EditableFM(path_md.parent, dry_run=True)
    page.load(path_md.name)
    page.fm['title'] = cleanBibTexString(e.fields['title'])
    authors = []
    for p in e.persons['author']:
        p: Person

        authors.append(findContentAuthor(p))

    date = eDate(e)
    if date is None:
        date = datetime.date(int(e.fields['year']), month=1, day=1)

    page.fm['authors'] = authors
    page.fm["date"] = date.isoformat()
    # page.fm["publishDate"] = timestamp
    pubtype = PUB_TYPES.get(e.type, PublicationType.Uncategorized)
    # Publication name.
    publication = ''
    for k in ['booktitle', 'journal', 'publisher']:
        if k in e.fields:
            publication = f'*{html.escape(e.fields[k])}*'
            break
    page.fm["publication"] = publication
    page.fm["publication"] = e.fields.get('journal', '')
    page.fm["publication_types"] = [str(pubtype.value)]
    page.fm["abstract"] = html.escape(e.fields.get('abstract', ''))

    tags = clean_bibtex_tags(e.fields.get('keywords', ''))
    page.fm['tags'] = tags

    links = []
    url_str = cleanBibTexString(e.fields.get('url', ''))

    if url_str != '':
        if re.search(r'\.pdf$', url_str):
            page.fm["url_pdf"] = url_str
        else:
            links += [{"name": "URL", "url": url_str}]

    page.fm['links'] = links

    if 'doi' in e.fields:
        page.fm["doi"] = cleanBibTexString(e.fields["doi"])

    page.dry_run = dry_run
    page.dump()
    return True


def loadDatabase(db: Union[str, pathlib.Path, BibliographyData]) -> BibliographyData:
    if isinstance(db, BibliographyData):
        return db

    pybtex.errors.strict = False
    if isinstance(db, (str, pathlib.Path)):
        return pybtex.database.parse_file(db)

    raise Exception(f'Cannot open as BibliographyData: {db}')


def eDate(e: Entry) -> datetime.date:
    y = e.fields.get('year')

    try:
        y = int(y)
    except (ValueError, TypeError):
        return None

    for k in ['month', 'DA', 'date']:
        month = e.fields.get(k)
        if not month:
            continue

        if re.search(r'^(\w+|\w+ \d+)$', month):
            month = f'{y} {month}'

        d = None
        for rxDate, pattern in DATE_PATTERNS:
            match = rxDate.match(month)
            if match:
                d = datetime.datetime.strptime(match.group(), pattern)
                if '%Y' not in pattern:
                    d = datetime.datetime(y, month=d.month, day=d.day)
                return d.date()

    return None


def eInfo(e: Entry) -> str:
    info = f'{e.key}' \
           f' {e.persons["author"][0].last_names[0]}' \
           f' ({e.fields.get("year", "<MISSING YEAR>")}) ' \
           f' "{e.fields.get("title", "<MISSING TITLE>")}"'
    return info


def entryFromDOI(e: Entry) -> Entry:
    doi = e.fields.get('doi')
    success, bib = get_bib_from_doi(doi)
    bib: str
    if not success:
        print(f'Unable to load DOI: {doi} {eInfo(e)}', file=sys.stderr)
        return None

    for k, v in REPLACE.items():
        bib = bib.replace(k, v)
    return Entry.from_string(bib, 'bibtex')


def verifyDatabase(db, remove_invalid: bool = True, trytofix: bool = True) -> Tuple[bool, BibliographyData, List[str]]:
    db = loadDatabase(db)
    db2 = BibliographyData()
    pybtex.errors.strict = False
    errors = []

    for e in db.entries.values():
        e = copy.deepcopy(e)

        y = int(e.fields.get('year'))
        if not 1950 < y <= datetime.date.today().year + 1:
            errors.append(eInfo(e) + f'\n\tinvalid year: {y}')
            if remove_invalid:
                continue

        doi = e.fields.get('doi')
        if doi is None:
            errors.append(eInfo(e) + '\n\tmissing doi')
            if remove_invalid:
                continue

        url = e.fields.get('url')

        if url:
            purl = urllib.parse.urlparse(url)
            if not bool(purl.scheme):
                errors.append(eInfo(e) +
                              f'\n\tinvalid url: {url}')
                del e.fields['url']
            elif not url.startswith('http'):
                del e.fields['url']
                u2 = None
                for c in url.split(' '):
                    if c.startswith('http'):
                        e.fields['url'] = u2
                        break

        date = eDate(e)
        if not isinstance(date, datetime.datetime):
            errors.append(eInfo(e) +
                          f'\n\tunable to extract month: '
                          f'"date"={e.fields.get("date")} '
                          f'"month"={e.fields.get("month")} '
                          f'"DA"={e.fields.get("DA")}')

            if trytofix:
                e.fields['date'] = datetime.date(y, month=1, day=1).isoformat()
                date = eDate(e)
                s = ""

        if not isinstance(date, datetime.date) and remove_invalid:
            continue

        e2 = copy.copy(e)
        db2.add_entry(e2.key, e2)

    return len(errors) == 0, db2, errors


def fixKeys(db: BibliographyData) -> BibliographyData:
    """
    Create a copy of the literature database with new entry keys.
    The new keys are grouped by 1st-author and year

    1. one publication in year 2024: author_2024
    2. multiple publication in year 2024: author_2024a, author_2024b, ....

    :param db: BibliographyData
    :return: BibliographyData
    """
    db = loadDatabase(db)
    db2 = BibliographyData()

    entries = db.entries.values()
    print(f'Fix entry keys for {len(entries)} entries.')
    # group publications by 1st author and year
    AUTHORS = dict()
    for e in entries:
        e: pybtex.database.Entry
        y = e.fields['year']
        a = '-'.join(e.persons['author'][0].last_names)
        k = (a, y)
        AUTHORS[k] = AUTHORS.get(k, []) + [e]

    alt = 'abcdefghijklmnopqrstuvwxyz'
    for (a, y), entries in AUTHORS.items():
        entries = copy.deepcopy(entries)
        if len(entries) == 1:
            entries[0].key = f'{a}_{y}'
        else:
            for i, e in enumerate(
                    sorted(entries, key=lambda e: e.fields.get('date', ''))):
                e.key = f'{a}_{y}{alt[i]}'
        for e in entries:
            db2.add_entry(e.key, e)

    return db2


def updatePublications(enforce_download: bool = False,
                       verify_only: bool = False,
                       dry_run: bool = False):
    pathBIB = downloadReferences(enforce=enforce_download)

    assert pathBIB.is_file()

    pathLog = pathBIB.parent / re.sub(r'\.(ris|bib)$', '.log', pathBIB.name)
    db = loadDatabase(pathBIB)
    success, db2, errors = verifyDatabase(db)

    if not success:
        print(f'Errors/Inconsistencies in {pathBIB}:')
        errors = sorted(errors, key=lambda line: int(line.split(' ')[0]))
        errorInfo = '\n'.join(errors)
        print(errorInfo, file=sys.stderr)
        with open(pathLog, 'w', encoding='utf8') as f:
            f.write(errorInfo)

    if verify_only:
        return

    db2 = fixKeys(db2)
    entries = db2.entries.values()

    n = len(entries)
    os.makedirs(DIR_PUBLICATION, exist_ok=True)

    ENTRIES_OLD = set(e.name for e in os.scandir(DIR_PUBLICATION) if e.is_dir())
    UPDATED = set()
    for i, e in enumerate(entries):
        path_entry = DIR_PUBLICATION / e.key
        success = write_publication(path_entry, e, dry_run=dry_run)
        print('{}/{} ({:2.2f}) "{}"'.format(i + 1, n, 100. * (i + 1) / n, e.key))

        if success:
            UPDATED.add(path_entry.name)

    # summary
    ENTRIES_NEW = UPDATED - ENTRIES_OLD
    ENTRIES_DEL = ENTRIES_OLD - UPDATED

    print(f'Updated entries: {len(UPDATED)}')
    print(f'New entries: {len(ENTRIES_NEW)}')
    print(f'Removable entries: {len(ENTRIES_DEL)}')

    if len(ENTRIES_DEL) > 0:
        print('\nCheck Folders an remove manually:')
        for n in ENTRIES_DEL:
            print(DIR_PUBLICATION / n)

    print('Update done')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update content/publications',
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-d', '--dry_run',
                        required=False,
                        default=False,
                        help='Just report changes to content/publications but do not write anything',
                        action='store_true')
    parser.add_argument('-v', '--verify_only',
                        required=False,
                        default=False,
                        help='Verify the entries in literature database only',
                        action='store_true')
    parser.add_argument('-e', '--enforce_download',
                        required=False,
                        default=False,
                        help='Enforces the download of the literature database, '
                             'overwriting an existing local *.ris file.',
                        action='store_true')

    args = parser.parse_args()

#    updatePublications(enforce_download=args.enforce_download,
#                       dry_run=args.dry_run,
#                       verify_only=args.verify_only)
    updatePublications(enforce_download=True,
                       dry_run=True,
                       verify_only=False)
