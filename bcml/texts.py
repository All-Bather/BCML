# Copyright 2019 Nicene Nerd <macadamiadaze@gmail.com>
# Licensed under GPLv3+
import copy
import csv
import io
import multiprocessing
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import List, Union

import rstb
import rstb.util
import sarc
import wszst_yaz0
import xxhash
import yaml

from bcml import util, rstable
from bcml.util import BcmlMod

text_exclusions = [
    'ErrorMessage',
    'LayoutMsg',
    'StaffRoll'
]


def get_msbt_hashes(lang: str = 'USen') -> {}:
    """
    Gets the MSBT hash table for the given language, or US English by default

    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :returns: A dictionary of MSBT files and their vanilla hashes.
    :rtype: dict of str: str
    """
    if not hasattr(get_msbt_hashes, 'texthashes'):
        get_msbt_hashes.texthashes = {}
        hash_table = util.get_exec_dir() / 'data' / 'msyt' / \
            f'Msg_{lang}_hashes.csv'
        if hash_table.exists():
            get_msbt_hashes.texthashes[lang] = {}
            with hash_table.open('r') as hf:
                csv_loop = csv.reader(hf)
                for row in csv_loop:
                    get_msbt_hashes.texthashes[lang][row[0]] = row[1]
        elif util.get_game_file(f'Pack/Bootup_{lang}.pack').exists():
            get_msbt_hashes.texthashes[lang] = {}
            with util.get_game_file(f'Pack/Bootup_{lang}.pack').open('rb') as bf:
                bootup_pack = sarc.read_file_and_make_sarc(bf)
            msg_bytes = wszst_yaz0.decompress(
                bootup_pack.get_file_data(f'Message/Msg_{lang}.product.ssarc'))
            msg_pack = sarc.SARC(msg_bytes)
            for msbt in msg_pack.list_files():
                get_msbt_hashes.texthashes[lang][msbt] = xxhash.xxh32(
                    msg_pack.get_file_data(msbt)).hexdigest()
    return get_msbt_hashes.texthashes[lang]


def extract_ref_msyts(lang: str = 'USen', for_merge: bool = False, tmp_dir: Path = util.get_work_dir() / 'tmp_text'):
    """
    Extracts the reference MSYT texts for the given language to a temp dir

    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :param for_merge: Whether the output is to be merged (or as reference), defaults to False
    :type for_merge: bool
    :param tmp_dir: The temp directory to extract to, defaults to "tmp_text" in BCML's working directory.
    :type tmp_dir: :class:`pathlib.Path`, optional
    """
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    with util.get_game_file(f'Pack/Bootup_{lang}.pack').open('rb') as bf:
        bootup_pack = sarc.read_file_and_make_sarc(bf)
    msg_bytes = wszst_yaz0.decompress(
        bootup_pack.get_file_data(f'Message/Msg_{lang}.product.ssarc'))
    msg_pack = sarc.SARC(msg_bytes)
    if not for_merge:
        merge_dir = tmp_dir / 'ref'
    else:
        merge_dir = tmp_dir / 'merged'
    msg_pack.extract_to_dir(str(merge_dir))
    msbt_to_msyt(merge_dir)


def _msyt_file(file):
    subprocess.call([str(util.get_exec_dir() / "helpers" / "msyt.exe"),
                     'export', str(file)], creationflags=util.CREATE_NO_WINDOW)


def msbt_to_msyt(tmp_dir: Path = util.get_work_dir() / 'tmp_text'):
    """ Converts MSBTs in given temp dir to MSYTs """
    subprocess.run([str(util.get_exec_dir() / 'helpers' / 'msyt.exe'),
                    'export', '-d', str(tmp_dir)], creationflags=util.CREATE_NO_WINDOW)
    fix_msbts = [msbt for msbt in tmp_dir.rglob(
        '**/*.msbt') if not msbt.with_suffix('.msyt').exists()]
    if len(fix_msbts) > 0:
        print('Some MSBTs failed to convert. Trying again individually...')
        p = multiprocessing.Pool(processes=min(
            multiprocessing.cpu_count(), len(fix_msbts)))
        out = p.map(_msyt_file, fix_msbts)
        p.close()
        p.join()
        fix_msbts = [msbt for msbt in tmp_dir.rglob(
            '**/*.msbt') if not msbt.with_suffix('.msyt').exists()]
    if len(fix_msbts) > 0:
        print(
            f'{len(fix_msbts)} MSBT files failed to convert. They will not be merged.')
    for msbt_file in tmp_dir.rglob('**/*.msbt'):
        Path(msbt_file).unlink()
    return fix_msbts


def msyt_to_msbt(tmp_dir: Path = util.get_work_dir() / 'tmp_text'):
    """ Converts merged MSYTs in given temp dir to MSBTs """
    msyt_bin = util.get_exec_dir() / 'helpers' / 'msyt.exe'
    merge_dir = tmp_dir / 'merged'
    m_args = [str(msyt_bin), 'create', '-d', str(merge_dir),
              '-p', 'wiiu', '-o', str(merge_dir)]
    subprocess.run(m_args, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, creationflags=util.CREATE_NO_WINDOW)
    for merged_msyt in merge_dir.rglob('**/*.msyt'):
        merged_msyt.unlink()


def bootup_from_msbts(lang: str = 'USen', msbt_dir: Path = util.get_work_dir() / 'tmp_text' / 'merged') -> (Path, int):
    """
    Generates a new Bootup_XXxx.pack from a directory of MSBT files

    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :param msbt_dir: The directory to pull MSBTs from, defaults to "tmp_text/merged" in BCML's working directory.
    :type msbt_dir: :class:`pathlib.Path`, optional
    :returns: A tuple with the path to the new Bootup_XXxx.pack and the RSTB size of the new Msg_XXxx.product.sarc
    :rtype: (:class:`pathlib.Path`, int)
    """
    new_boot_path = msbt_dir.parent / f'Bootup_{lang}.pack'
    with new_boot_path.open('wb') as new_boot:
        s_msg = sarc.SARCWriter(True)
        for new_msbt in msbt_dir.rglob('**/*.msbt'):
            with new_msbt.open('rb') as f_new:
                s_msg.add_file(str(new_msbt.relative_to(msbt_dir)
                                   ).replace('\\', '/'), f_new.read())
        new_msg_stream = io.BytesIO()
        s_msg.write(new_msg_stream)
        unyaz_bytes = new_msg_stream.getvalue()
        rsize = rstb.SizeCalculator().calculate_file_size_with_ext(unyaz_bytes, True, '.sarc')
        new_msg_bytes = wszst_yaz0.compress(unyaz_bytes)
        s_boot = sarc.SARCWriter(True)
        s_boot.add_file(f'Message/Msg_{lang}.product.ssarc', new_msg_bytes)
        s_boot.write(new_boot)
    return new_boot_path, rsize


def write_msbt(msbt_info: tuple):
    msbt_path, msbt_data = msbt_info
    msbt_path.parent.mkdir(parents=True, exist_ok=True)
    with msbt_path.open(mode='wb') as f_msbt:
        f_msbt.write(msbt_data)
    return None


def get_modded_msyts(msg_sarc: sarc.SARC, lang: str = 'USen', tmp_dir: Path = util.get_work_dir() / 'tmp_text') \
        -> (list, dict):
    """
    Gets a list of modified game text files in a given message SARC

    :param msg_sarc: The message SARC to scan for changes.
    :type msg_sarc: :class:`sarc.SARC`
    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :param tmp_dir: The temp directory to use, defaults to "tmp_text" in BCML's working directory.
    :type tmp_dir: :class:`pathlib.Path`, optional
    :returns: Returns a tuple containing a list of modded text files and a dict of new text
    files with their contents.
    :rtype: (list of str, dict of str: bytes)
    """
    hashes = get_msbt_hashes(lang)
    modded_msyts = []
    added_msbts = {}
    write_msbts = []
    for msbt in msg_sarc.list_files():
        if any(exclusion in msbt for exclusion in text_exclusions):
            continue
        m_data = msg_sarc.get_file_data(msbt)
        m_hash = xxhash.xxh32(m_data).hexdigest()
        if msbt not in hashes:
            added_msbts[msbt] = m_data
        elif m_hash != hashes[msbt]:
            write_msbts.append((tmp_dir / msbt, m_data.tobytes()))
            modded_msyts.append(msbt.replace('.msbt', '.msyt'))
    p = multiprocessing.Pool()
    p.map(write_msbt, write_msbts)
    p.close()
    p.join()
    return modded_msyts, added_msbts


def store_added_texts(new_texts: dict) -> sarc.SARCWriter:
    """ Creates a SARC to store mod-original MSBTs """
    text_sarc = sarc.SARCWriter(True)
    for msbt in new_texts:
        text_sarc.add_file(msbt, new_texts[msbt])
    return text_sarc


def threaded_compare_texts(msyt: Path, tmp_dir: Path, ref_dir: Path) -> (str, dict):
    rel_path = str(msyt.relative_to(ref_dir)).replace('\\', '/')
    with (ref_dir / rel_path).open('r', encoding='utf-8') as ref_file:
        ref_text = yaml.safe_load(ref_file)
    try:
        with (tmp_dir / rel_path).open('r', encoding='utf-8') as mod_file:
            mod_text = yaml.safe_load(mod_file)
    except:
        return rel_path, None
    text_edits = {
        'entries': {}
    }
    for entry in mod_text['entries']:
        if util.is_yaml_modded(entry, ref_text, mod_text):
            text_edits['entries'][entry] = copy.deepcopy(
                mod_text['entries'][entry])
    return rel_path, text_edits


def get_modded_texts(modded_msyts: list, tmp_dir: Path = util.get_work_dir() / 'tmp_text') -> dict:
    """
    Builds a dictionary of all edited text entries in modded MSYTs

    :param modded_msyts: A list of MSYT files that have been modified.
    :type modded_msyts: list of str
    :param tmp_dir: The temp directory to use, defaults to "tmp_text" in BCML's working directory.
    :type tmp_dir: :class:`pathlib.Path`
    :returns: Returns a dictionary of modified MSYT text entries.
    :rtype: dict 
    """
    ref_dir = tmp_dir / 'ref'
    text_edits = {}
    check_msyts = [msyt for msyt in list(ref_dir.rglob('**/*.msyt'))
                   if str(msyt.relative_to(ref_dir)).replace('\\', '/') in modded_msyts]
    num_threads = min(multiprocessing.cpu_count(), len(check_msyts))
    thread_checker = partial(threaded_compare_texts,
                             tmp_dir=tmp_dir, ref_dir=ref_dir)
    p = multiprocessing.Pool(processes=num_threads)
    edit_results = p.map(thread_checker, check_msyts)
    p.close()
    p.join()
    for edit in edit_results:
        rel_path, edits = edit
        if edits == None:
            print(f'{rel_path} is corrupt and will not be merged.')
            continue
        if len(edits['entries']) > 0:
            text_edits[rel_path] = edits
    return text_edits


def get_text_mods_from_bootup(bootup_path: Union[Path, str], tmp_dir: Path = util.get_work_dir() / 'tmp_text',
                              verbose: bool = False):
    """
    Detects modifications to text files inside a given Bootup_XXxx.pack

    :param bootup_path: Path to the Bootup_XXxx.pack file.
    :type bootup_path: :class:`pathlib.Path`
    :param tmp_dir: The temp directory to use, defaults to "tmp_text" in BCML's working directory.
    :type tmp_dir: :class:`pathlib.Path`
    :param verbose: Whether to display more detailed output, defaults to False.
    :type verbose: bool, optional
    :returns: Return a tuple containing a dict of modded text entries, a SARC containing added text
    MSBTs, and the game language of the bootup pack.
    :rtype: (dict, :class:`sarc.SARCWriter`, str)
    """
    lang = util.get_file_language(bootup_path)
    print(f'Scanning text modifications for language {lang}...')
    d = '  '

    if verbose:
        print(f'{d}Loading reference texts...')
    extract_ref_msyts(lang)

    if verbose:
        print(f'{d}Identifying modified text files...')
    with open(bootup_path, 'rb') as bf:
        bootup_sarc = sarc.read_file_and_make_sarc(bf)
    msg_bytes = wszst_yaz0.decompress(
        bootup_sarc.get_file_data(f'Message/Msg_{lang}.product.ssarc'))
    msg_sarc = sarc.SARC(msg_bytes)
    if not msg_sarc:
        print(
            f'Failed to open Msg_{lang}.product.ssarc, could not analyze texts')
    modded_msyts, added_msbts = get_modded_msyts(msg_sarc, lang)
    added_text_store = None
    if len(added_msbts) > 0:
        added_text_store = store_added_texts(added_msbts)

    if verbose:
        for modded_text in modded_msyts:
            print(f'{d}{d}{modded_text} has been changed')
        for added_text in added_msbts:
            print(f'{d}{d}{added_text} has been added')

    problems = msbt_to_msyt()
    for problem in problems:
        msyt_name = problem.relative_to(
            tmp_dir).with_suffix('.msyt').as_posix()
        modded_msyts.remove(msyt_name)
    if verbose:
        print(f'{d}Scanning texts files for modified entries...')
    modded_texts = get_modded_texts(modded_msyts)
    s_modded = 's' if len(modded_texts) != 1 else ''
    s_added = 's' if len(added_msbts) != 1 else ''
    print(f'Language {lang} has total {len(modded_texts)} modified text file{s_modded} and {len(added_msbts)}'
          f' new text file{s_added}')
    shutil.rmtree(tmp_dir)
    return modded_texts, added_text_store, lang


def get_text_mods(lang: str = 'USen') -> List[BcmlMod]:
    """
    Gets all install text mods for a given language

    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :return: Returns a list of all text mods installed for the selected language.
    :rtype: list of :class:`bcml.util.BcmlMod`
    """
    tmods = [mod for mod in util.get_installed_mods() if (
        mod.path / 'logs' / f'texts_{lang}.yml').exists()]
    return sorted(tmods, key=lambda mod: mod.priority)


def get_modded_text_entries(lang: str = 'USen') -> List[dict]:
    """
    Gets a list containing all modified text entries installed
    """
    textmods = []
    for mod in sorted(util.get_modpack_dir().rglob(f'logs/texts_{lang}.yml')):
        with mod.open('r', encoding='utf-8') as mod_text:
            textmods.append(yaml.safe_load(mod_text))
    return textmods


def get_modded_languages(mod: Path) -> []:
    """ Gets all languages with modded texts for a given mod """
    text_langs = []
    for text_lang in (mod / 'logs').glob('*text*'):
        lang = util.get_file_language(text_lang)
        if lang not in text_langs:
            text_langs.append(lang)
    return text_langs


def get_added_text_mods(lang: str = 'USen') -> List[sarc.SARC]:
    """
    Gets a list containing all mod-original texts installed
    """
    textmods = []
    for mod in sorted(util.get_modpack_dir().rglob(f'logs/newtexts_{lang}.sarc')):
        with mod.open('rb') as sf:
            textmods.append(sarc.read_file_and_make_sarc(sf))
    return textmods


def threaded_merge_texts(msyt: Path, merge_dir: Path, text_mods: List[dict], verbose: bool) -> (int, str):
    rel_path = str(msyt.relative_to(merge_dir)).replace('\\', '/')
    should_bother = False
    merge_count = 0
    for textmod in text_mods:
        if rel_path in textmod:
            should_bother = True
    if not should_bother:
        if verbose:
            print(f'  Skipping {rel_path}, no merge needed')
        return 0, None

    with msyt.open('r', encoding='utf-8') as f_ref:
        merged_text = yaml.safe_load(f_ref)

    for textmod in text_mods:
        diff_found = False
        if rel_path in textmod:
            if textmod[rel_path]['entries'] == merged_text['entries']:
                continue
            for entry in textmod[rel_path]['entries']:
                diff_found = True
                merged_text['entries'][entry] = copy.deepcopy(
                    textmod[rel_path]['entries'][entry])
        if diff_found:
            merge_count += 1

    with msyt.open('w', encoding='utf-8') as f_ref:
        yaml.dump(merged_text, f_ref)
    return merge_count, rel_path


def merge_texts(lang: str = 'USen', tmp_dir: Path = util.get_work_dir() / 'tmp_text', verbose: bool = False):
    """
    Merges installed text mods and saves the new Bootup_XXxx.pack, fixing the RSTB if needed

    :param lang: The game language to use, defaults to USen.
    :type lang: str, optional
    :param tmp_dir: The temp directory to extract to, defaults to "tmp_text" in BCML's local appdata.
    :type tmp_dir: :class:`pathlib.Path`, optional
    :param verbose: Whether to display more detailed output, defaults to False
    :type verbose: bool, optional
    """
    print(f'Loading text mods for language {lang}...')
    text_mods = get_modded_text_entries(lang)
    if len(text_mods) == 0:
        print('No text merging necessary.')
        old_path = util.get_master_modpack_dir() / 'content' / 'Pack' / \
            f'Bootup_{lang}.pack'
        if old_path.exists():
            old_path.unlink()
        return
    if verbose:
        print(f'  Found {len(text_mods)} text mods to be merged')

    if tmp_dir.exists():
        if verbose:
            print('Cleaning temp directory...')
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print('Extracting clean MSYTs...')
    extract_ref_msyts(lang, for_merge=True, tmp_dir=tmp_dir)
    merge_dir = tmp_dir / 'merged'
    merge_dir.mkdir(parents=True, exist_ok=True)

    print('Merging modified text files...')
    modded_text_files = list(merge_dir.rglob('**/*.msyt'))
    num_threads = min(multiprocessing.cpu_count(), len(modded_text_files))
    p = multiprocessing.Pool(processes=num_threads)
    thread_merger = partial(
        threaded_merge_texts, merge_dir=merge_dir, text_mods=text_mods, verbose=verbose)
    results = p.map(thread_merger, modded_text_files)
    p.close()
    p.join()
    for merge_count, rel_path in results:
        if merge_count > 0:
            print(f'  Merged {merge_count} versions of {rel_path}')
    print('Generating merged MSBTs...')
    msyt_to_msbt(tmp_dir)

    added_texts = get_added_text_mods(lang)
    if len(added_texts) > 0:
        print('Adding mod-original MSBTs...')
        for added_text in added_texts:
            for msbt in added_text.list_files():
                Path(merge_dir / msbt).parent.mkdir(parents=True, exist_ok=True)
                with open(Path(merge_dir / msbt), 'wb') as xf:
                    xf.write(added_text.get_file_data(msbt).tobytes())

    print(f'Creating new Bootup_{lang}.pack...')
    tmp_boot_path, msg_rstb = bootup_from_msbts(lang)
    merged_boot_path = util.get_modpack_dir() / '9999_BCML' / 'content' / \
        'Pack' / f'Bootup_{lang}.pack'
    if merged_boot_path.exists():
        if verbose:
            print(f'  Removing old Bootup_{lang}.pack...')
        merged_boot_path.unlink()
    merged_boot_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(tmp_boot_path), str(merged_boot_path))

    rstb_path = util.get_modpack_dir() / '9999_BCML' / 'content' / 'System' / 'Resource' /\
                                         'ResourceSizeTable.product.srsizetable'
    if rstb_path.exists():
        table: rstb.ResourceSizeTable = rstb.util.read_rstb(
            str(rstb_path), True)
    else:
        table = rstable.get_stock_rstb()
    msg_path = f'Message/Msg_{lang}.product.sarc'
    if table.is_in_table(msg_path):
        print('Correcting RSTB...')
        table.delete_entry(msg_path)
    rstb_path.parent.mkdir(parents=True, exist_ok=True)
    rstb.util.write_rstb(table, str(rstb_path), True)