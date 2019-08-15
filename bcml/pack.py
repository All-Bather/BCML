# Copyright 2019 Nicene Nerd <macadamiadaze@gmail.com>
# Licensed under GPLv3+
import csv
import io
import os
import xxhash
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import List, Union

import sarc
import wszst_yaz0

from bcml import data, util
from bcml.util import BcmlMod


def get_pack_mods() -> List[BcmlMod]:
    """
    Gets a list of all installed pack mods

    :return: Returns a list of mods that modify pack files
    :rtype: list of :class:`bcml.util.BcmlMod`
    """
    pmods = [mod for mod in util.get_installed_mods() if (
        mod.path / 'logs' / 'packs.log').exists()]
    return sorted(pmods, key=lambda mod: mod.priority)


def get_modded_packs_in_mod(mod: Union[Path, str, BcmlMod]) -> List[str]:
    """
    Get all pack files modified by a given mod
    """
    path = mod if isinstance(mod, Path) else Path(
        mod) if isinstance(mod, str) else mod.path
    packs = []
    plog = path / 'logs' / 'packs.log'
    if not plog.exists():
        return []
    with plog.open('r') as rlog:
        csv_loop = csv.reader(rlog)
        for row in csv_loop:
            packs.append(row[1])
    return packs


def get_modded_sarcs() -> dict:
    """
    Gets all installed SARC modifications, along with their priorities

    :returns: Returns a dict of dicts with the path of each modified SARC and its priority for each canonical file.
    :rtype: dict of str: list of dict of str: int
    """
    packs = {}
    hashes = util.get_hash_table()
    for mod in get_pack_mods():
        with (mod.path / 'logs' / 'packs.log').open('r') as rlog:
            csv_loop = csv.reader(rlog)
            for row in csv_loop:
                if ('Bootup_' in row[0] and 'Bootup_Graphics' not in row[0]) \
                        or (row[0] == 'name') or row[0] not in hashes:
                    continue
                filepath = mod.path / str(row[1])
                if row[0] not in packs:
                    packs[row[0]] = []
                packs[row[0]].append({
                    'path': filepath,
                    'rel_path': str(row[1]),
                    'priority': mod.priority
                })
    return packs


def get_sarc_versions(name: str, mod_list: dict) -> List[dict]:
    """
    Gets all of the modified versions of given SARC

    :param name: The canonical path of the SARC.
    :type name: str
    :param mod_list: The dict containing all modded SARC entries.
    :type mod_list: dict
    :returns: Returns a list of dicts containing each modified version
    of the given SARC with metadata.
    :rtype: list of dict of str: :class:`sarc.SARC`, str: int, str: int, str: str
    """
    sarc_list = []
    for pack in mod_list[name]:
        try:
            with open(pack['path'], 'rb') as opened_pack:
                o_sarc = sarc.read_file_and_make_sarc(opened_pack)
                if o_sarc:
                    sarc_list.append({
                        'pack': o_sarc,
                        'priority': pack['priority'],
                        'nest_level': 1,
                        'name': name,
                        'base': False
                    })
        except FileNotFoundError:
            pass
    try:
        base_file = util.get_game_file(mod_list[name][0]['rel_path'])
        with base_file.open('rb') as sf:
            b_sarc = sarc.read_file_and_make_sarc(sf)
            if b_sarc:
                sarc_list.insert(0, {
                    'pack': b_sarc,
                    'priority': 1,
                    'nest_level': 1,
                    'name': name,
                    'base': True
                })
    except FileNotFoundError:
        pass
    return sarc_list


def merge_sarcs(sarc_list, verbose: bool = False, loose_files: dict = None) -> tuple:
    """
    Merges a list of SARC packs and returns the changes

    :param sarc_list: A list of dicts with SARCs to be merged and their metadata. 
    Each entry must contain keys "pack", "priority", "nest_level", and "name".
    :type sarc_list: list
    :param verbose: Whether to display more detailed output, defaults to False
    :type verbose: bool, optional
    :returns: Returns tuple with a merged SARC and a list of changes made.
    :rtype: (:class:`sarc.SARCWriter`, list of str)
    """
    hashes = util.get_hash_table()
    sarc_log = []
    sarc_list = sorted(sarc_list, key=lambda pack: pack['priority'])
    try:
        base_sarc = next(iter([msarc['pack']
                               for msarc in sarc_list if msarc['base']]))
    except StopIteration:
        base_sarc = sarc_list[-1]['pack']

    new_sarc = sarc.make_writer_from_sarc(base_sarc)
    output_spaces = '  ' * sarc_list[-1]['nest_level']

    modded_files = {}
    modded_sarcs = {}
    can_skip = True
    priority = 100
    for msarc in sarc_list:
        pack = msarc['pack']
        priority = msarc['priority']
        for file in pack.list_files():
            if file not in base_sarc.list_files():
                new_sarc.add_file(file, pack.get_file_data(file).tobytes())
                continue
            rfile = file.replace('.s', '.')
            fdata = util.unyaz_if_needed(
                pack.get_file_data(file).tobytes())
            if rfile not in hashes or hashes[rfile] != xxhash.xxh32(fdata).hexdigest():
                ext = os.path.splitext(rfile)[1]
                if ext in util.SARC_EXTS:
                    try:
                        nest_pack = sarc.SARC(fdata)
                    except ValueError:
                        modded_files[file] = priority
                        continue
                    modded_sarc = {
                        'pack': nest_pack,
                        'priority': priority,
                        'nest_level': sarc_list[-1]['nest_level'] + 1,
                        'name': rfile,
                        'base': False
                    }
                    can_skip = False
                    if file not in modded_sarcs:
                        modded_sarcs[file] = []
                    modded_sarcs[file].append(modded_sarc)
                else:
                    modded_files[file] = priority

    # for modded_file in modded_files.keys():
    #    if not modded_files[modded_file] == priority:
    #        can_skip = False
    # if can_skip:
    #    if verbose:
    #        sarc_log.append(f'{output_spaces}No merges necessary, skipping')
    #    return new_sarc, sarc_log

    for modded_file in modded_files.keys():
        if modded_file in base_sarc.list_files():
            new_sarc.delete_file(modded_file)
        p = filter(lambda x: x['priority'] ==
                   modded_files[modded_file], sarc_list).__next__()
        new_data = p['pack'].get_file_data(modded_file).tobytes()
        new_sarc.add_file(modded_file, new_data)
        if verbose:
            sarc_log.append(f'{output_spaces}Updated file {modded_file}')

    merged_sarcs = []
    for mod_sarc_list in modded_sarcs:
        if len(modded_sarcs[mod_sarc_list]) == 0:
            continue
        new_pack, sub_log = merge_sarcs(
            modded_sarcs[mod_sarc_list], verbose, loose_files=loose_files)
        sarc_log.extend(sub_log)
        merged_sarcs.append({
            'file': mod_sarc_list,
            'pack': new_pack
        })

    for merged_sarc in merged_sarcs:
        if merged_sarc['file'] in base_sarc.list_files():
            new_sarc.delete_file(merged_sarc['file'])
        new_stream = io.BytesIO()
        merged_sarc['pack'].write(new_stream)
        new_data = new_stream.getvalue()
        del new_stream
        if '.s' in merged_sarc['file'] and not merged_sarc['file'].endswith('.sarc'):
            new_data = wszst_yaz0.compress(new_data)
        new_sarc.add_file(merged_sarc['file'], new_data)
        del new_data

    for file in base_sarc.list_files():
        if file in loose_files:
            if file not in modded_files or loose_files[file] > modded_files[file]:
                mod = util.get_mod_by_priority(loose_files[file])
                prefix = 'content' if not file.startswith(
                    'Aoc/0010') else 'aoc/0010'
                modded_bytes = (mod / 'content' /
                                file.replace('Aoc/0010', '')).read_bytes()
                new_sarc.delete_file(file)
                new_sarc.add_file(file, modded_bytes)

    if sarc_list[-1]['nest_level'] > 1:
        if verbose:
            sarc_log.append(
                f'{output_spaces[4:]}Updated nested pack {sarc_list[-1]["name"]}')

    if verbose:
        sarc_log.append(
            f'{output_spaces[4:]}Merged {len(sarc_list)} versions of {sarc_list[-1]["name"]}')
    return new_sarc, sarc_log


def threaded_merge_sarcs(pack, modded_sarcs, verbose, modded_files):
    output_path = Path(util.get_master_modpack_dir() /
                       modded_sarcs[pack][0]['rel_path'])
    versions = get_sarc_versions(pack, modded_sarcs)
    try:
        new_sarc, log = merge_sarcs(
            versions, verbose, loose_files=modded_files)
    except IndexError:
        return []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('wb') as of:
        if output_path.suffix.startswith('.s') and output_path.suffix != '.sarc':
            of.write(wszst_yaz0.compress(new_sarc.get_bytes()))
        else:
            new_sarc.write(of)
    return log


def merge_installed_packs(no_injection: bool = False, only_these: List[str] = None, verbose: bool = False, even_one: bool = False):
    """
    Merges all modified packs in installed BCML mods

    :param no_injection: Do not inject merged gamedata or savedata when possible, defaults to False
    :type no_injection: bool, optional
    :param verbose: Whether to display more detailed output, defaults to False
    :type verbose: bool, optional
    """
    print('Merging modified SARC packs...')
    modded_files = util.get_all_modded_files(only_loose=True)
    bcml_dir = util.get_master_modpack_dir()
    if only_these is None:
        if (bcml_dir / 'aoc').exists():
            print('Cleaning old aoc packs...')
            for file in (bcml_dir / 'aoc').rglob('**/*'):
                if file.is_file() and file.suffix in util.SARC_EXTS:
                    file.unlink()
        if (bcml_dir / 'content').exists():
            print('Cleaning old content packs...')
            for file in (bcml_dir / 'content').rglob('**/*'):
                if file.is_file() and file.suffix in util.SARC_EXTS and 'Bootup_' not in file.stem:
                    file.unlink()
    else:
        for file in only_these:
            if (bcml_dir / file).exists():
                (bcml_dir / file).unlink()
    print('Loading modded packs...')
    modded_sarcs = get_modded_sarcs()
    log_count = 0
    num_req = 1 if not even_one else 0
    sarcs_to_merge = [
        pack for pack in modded_sarcs if len(modded_sarcs[pack]) > num_req]
    if only_these is not None:
        sarcs_to_merge = [
            pack for pack in sarcs_to_merge if modded_sarcs[pack][0]['rel_path'] in only_these]
    if len(sarcs_to_merge) > 0:
        print(f'Processing {len(sarcs_to_merge)} packs...')
        partial_thread_merge = partial(
            threaded_merge_sarcs, modded_sarcs=modded_sarcs, verbose=verbose, modded_files=modded_files)
        num_threads = min(cpu_count() - 1, len(modded_sarcs))
        p = Pool(processes=num_threads)
        results = p.map(partial_thread_merge, sarcs_to_merge)
        p.close()
        p.join()
        logs = [log for sublog in results for log in sublog]
        log_count = len([log for log in logs if log !=
                         'No merges necessary, skipping'])
    else:
        log_count = 0
    print(f'Pack merging complete. Merged {log_count} packs.')
    if 'Pack/Bootup.pack' in modded_sarcs and not no_injection:
        if only_these is not None and 'content\\Pack\\Bootup.pack' not in only_these:
            return
        if (util.get_master_modpack_dir() / 'logs' / 'gamedata.log').exists():
            print('Injecting merged gamedata.sarc into Bootup.pack...')
            with (util.get_master_modpack_dir() / 'logs' / 'gamedata.sarc').open('rb') as gf:
                gamedata = sarc.read_sarc_and_make_writer(gf)
            data.inject_gamedata_into_bootup(gamedata)
        if (util.get_master_modpack_dir() / 'logs' / 'savedata.log').exists():
            print('Injecting merged savedataformat.sarc into Bootup.pack...')
            with (util.get_master_modpack_dir() / 'logs' / 'savedata.sarc').open('rb') as sf:
                savedata = sarc.read_sarc_and_make_writer(sf)
            data.inject_savedata_into_bootup(savedata)