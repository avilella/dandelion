#!/usr/bin/env python
# @Author: kt16
# @Date:   2020-05-12 14:01:32
# @Last Modified by:   Kelvin
# @Last Modified time: 2021-02-11 12:05:34

import sys
import os
from collections import defaultdict, Iterable
import pandas as pd
import numpy as np
from subprocess import run
from tqdm import tqdm
import re
import copy
from changeo.IO import readGermlines
import warnings
import scipy.sparse
import tables
import h5py
import networkx as nx
import bz2
import gzip
import _pickle as cPickle
try:
    from scanpy import logging as logg
except ImportError:
    pass


class Tree(defaultdict):
    '''
    Create a recursive defaultdict
    '''

    def __init__(self, value=None):
        super(Tree, self).__init__(Tree)
        self.value = value


def fasta_iterator(fh):
    '''
    Read in a fasta file as an iterator
    '''
    while True:
        line = fh.readline()
        if line.startswith('>'):
            break
    while True:
        header = line[1:-1].rstrip()
        sequence = fh.readline().rstrip()
        while True:
            line = fh.readline()
            if not line:
                break
            if line.startswith('>'):
                break
            sequence += line.rstrip()
        yield(header, sequence)
        if not line:
            return


def Write_output(out, file):
    '''
    general line writer
    '''
    fh = open(file, "a")
    fh.write(out)
    fh.close()
    return()


def dict_from_table(meta, columns):
    """
    Generates a dictionary from a dataframe
    Parameters
    ----------
    meta
        pandas dataframe or file path
    columns
        column names in dataframe

    Returns
    -------
    dictionary
    """
    if (isinstance(meta, pd.DataFrame)) & (columns is not None):
        meta_ = meta
        if len(columns) == 2:
            sample_dict = dict(zip(meta_[columns[0]], meta_[columns[1]]))
    elif (os.path.isfile(str(meta))) & (columns is not None):
        meta_ = pd.read_csv(meta, sep='\t', dtype='object')
        if len(columns) == 2:
            sample_dict = dict(zip(meta_[columns[0]], meta_[columns[1]]))

    sample_dict = clean_nan_dict(sample_dict)
    return(sample_dict)


def clean_nan_dict(d):
    """
    Parameters
    ----------
    d
        dictionary

    Returns
    -------
    dictionary with no NAs.
    """

    return {
        k: v
        for k, v in d.items()
        if v is not np.nan
    }


def flatten(l):
    """
    Parameters
    ----------
    l
        list

    Returns
    -------
    a flattened list.
    """
    for el in l:
        if isinstance(el, Iterable) and not isinstance(el, (str, bytes)):
            yield from flatten(el)
        else:
            yield el


def makeblastdb(ref):
    """
    Runs makeblastdb.

    Parameters
    ----------
    ref
        fasta file

    """

    cmd = ['makeblastdb',
           '-dbtype', 'nucl',
           '-parse_seqids',
           '-in', ref]
    run(cmd)


def bh(pvalues):
    """
    Computes the Benjamini-Hochberg FDR correction.

    Input:
        * pvals - vector of p-values to correct
    """
    n = int(pvalues.shape[0])
    new_pvalues = np.empty(n)
    values = [(pvalue, i) for i, pvalue in enumerate(pvalues)]
    values.sort()
    values.reverse()
    new_values = []
    for i, vals in enumerate(values):
        rank = n - i
        pvalue, index = vals
        new_values.append((n/rank) * pvalue)
    for i in range(0, int(n)-1):
        if new_values[i] < new_values[i+1]:
            new_values[i+1] = new_values[i]
    for i, vals in enumerate(values):
        pvalue, index = vals
        new_pvalues[index] = new_values[i]
    return new_pvalues

# def extract(d, keys):
#    return(dict((k, d[k]) for k in keys if k in d))


def load_data(obj):
    """
    Reads in or copy dataframe object and set sequence_id as index without dropping.

    Parameters
    ----------
    obj : DataFrame, str
        file path to .tsv file or pandas DataFrame object.

    Returns
    -------
    pandas DataFrame object.
    """
    if os.path.isfile(str(obj)):
        try:
            obj_ = pd.read_csv(obj, sep='\t')
        except FileNotFoundError as e:
            print(e)
    elif isinstance(obj, pd.DataFrame):
        obj_ = obj.copy()
    else:
        raise TypeError(
            "Either input is not of <class 'pandas.core.frame.DataFrame'> or file does not exist.")

    if 'sequence_id' in obj_.columns:
        obj_.set_index('sequence_id', drop=False, inplace=True)
    else:
        raise KeyError("'sequence_id' not found in columns of input")

    return(obj_)


def is_categorical(array_like):
    return array_like.dtype.name == 'category'


def type_check(dataframe, key):
    return dataframe[key].dtype == str or dataframe[key].dtype == object or is_categorical(dataframe[key]) or dataframe[key].dtype == bool


def retrieve_metadata(data, query, split, collapse, combine=False, locus='ig', split_locus=False, verbose=False):
    dat_dict = defaultdict(dict)
    dict_ = defaultdict(dict)
    metadata_ = defaultdict(dict)

    locus_dict1 = {'ig': 'IGH'}
    locus_dict2 = {'ig': ['IGK', 'IGL']}
    locus_dict3 = {'ig': 'H'}
    locus_dict4 = {'ig': 'L'}
    query_dict = dict(zip(data['sequence_id'], data[query]))

    if type_check(data, query):
        data[query].fillna('unassigned', inplace=True)

    typesoflocus = len(list(set(data['locus'])))

    if typesoflocus > 1:
        if split_locus:
            for loci in flatten([locus_dict1[locus]] + locus_dict2[locus]):
                tmp = data[data['locus'].isin([loci])].copy()
                if tmp.shape[0] > 0:
                    dat_dict[loci] = tmp.copy()
        else:
            tmp3 = data[data['locus'].isin([locus_dict1[locus]])].copy()
            tmp4 = data[data['locus'].isin(locus_dict2[locus])].copy()
            if tmp3.shape[0] > 0:
                dat_dict[locus_dict3[locus]] = tmp3.copy()
            if tmp4.shape[0] > 0:
                dat_dict[locus_dict4[locus]] = tmp4.copy()
    else:
        if verbose:
            warnings.warn(UserWarning(
                'Single locus type detected. Ignoring split = True and split_locus = True.'))
        dat_dict[locus_dict3[locus]] = data[data['locus'].isin(
            [locus_dict1[locus]])].copy()

    for d in dat_dict:
        tmp = Tree()
        for cell, seq in zip(dat_dict[d]['cell_id'], dat_dict[d]['sequence_id']):
            tmp[cell][seq].value = 1
        cells = []
        seqs = []
        for t in tmp:
            cells.append(t)
            seqs.append([s for s in tmp[t]])
        metadata_[d] = pd.DataFrame(seqs, index=cells)
        metadata_[d][pd.isnull(metadata_[d])] = np.nan

    if split_locus:
        H = locus_dict1[locus]
    else:
        H = locus_dict3[locus]

    if len(metadata_[H].columns) > 1:
        metadata_[H].columns = ['sequence_id_'+H+'_' +
                                str(x) for x in range(0, len(metadata_[H].columns))]
    else:
        metadata_[H].columns = ['sequence_id_'+H+'_0']

    if typesoflocus > 1:
        if split_locus:
            for L in locus_dict2[locus]:
                if len(metadata_[L].columns) > 1:
                    metadata_[L].columns = ['sequence_id_'+L+'_' +
                                            str(x) for x in range(0, len(metadata_[L].columns))]
                else:
                    metadata_[L].columns = ['sequence_id_'+L+'_0']
        else:
            L = locus_dict4[locus]
            if len(metadata_[L].columns) > 1:
                metadata_[L].columns = ['sequence_id_'+L+'_' +
                                        str(x) for x in range(0, len(metadata_[L].columns))]
            else:
                metadata_[L].columns = ['sequence_id_'+L+'_0']

    metadata_result = metadata_.copy()
    for l in metadata_:
        for x in metadata_[l]:
            metadata_result[l][x] = [query_dict[i] if i ==
                                     i else np.nan for i in metadata_[l][x]]

    if typesoflocus > 1:
        if not split_locus:
            results = retrieve_result_dict(
                query, data, metadata_result[locus_dict3[locus]], metadata_result[locus_dict4[locus]], locus, split, collapse, combine)
        else:
            results = retrieve_result_dict(query, data, metadata_result[locus_dict1[locus]], [
                                           metadata_result[L] for L in locus_dict2[locus]], locus, split, collapse, combine)
    else:
        results = retrieve_result_dict_singular(
            query, data, metadata_result[locus_dict3[locus]], locus, collapse, combine)
    return(results)


def retrieve_result_dict(query, data, meta_h, meta_l, locus='ig', split=True, collapse=True, combine=False, verbose=False):
    df_hl = defaultdict(dict)
    locus_dict1 = {'ig': 'IGH'}
    locus_dict2 = {'ig': ['IGK', 'IGL']}
    locus_dict3 = {'ig': 'H'}
    locus_dict4 = {'ig': 'L'}
    if len(meta_l) == 2 and type(meta_l) is list:
        H = locus_dict1[locus]
    else:
        H = locus_dict3[locus]
    if meta_h.shape[1] > 1:
        if collapse:
            newmeta_h = meta_h.copy()
            if type_check(meta_h, 'sequence_id_'+H+'_0'):
                newh = []
                for i in meta_h.index:
                    try:
                        newh.append(
                            '|'.join([h for h in list(dict.fromkeys(newmeta_h.loc[i])) if h == h]))
                    except:
                        newh.append('|'.join([str(h) for h in list(
                            dict.fromkeys(newmeta_h.loc[i])) if h == h]))
                newmeta_h['sequence_id_'+H+'_0'] = newh
                meta_h = pd.DataFrame(newmeta_h['sequence_id_'+H+'_0'].copy())
            else:
                collapse = False
                if verbose:
                    warnings.warn(UserWarning(
                        'Multiple heavy chain contigs mapping to the same cell barcode and/or query dtype is {}. Ignoring collapse = True.'.format(meta_h['sequence_id_'+H+'_0'].dtype.name)))
    if len(meta_l) == 2 and type(meta_l) is list:
        metadata_ = meta_h.join(meta_l[0]).join(meta_l[1])
    else:
        metadata_ = meta_h.join(meta_l)
    df_ = metadata_.copy()
    if type_check(meta_h, 'sequence_id_'+H+'_0'):
        if split:
            df_hl[H] = df_[list(meta_h.columns)].copy()
            if len(meta_l) == 2 and type(meta_l) is list:
                for x in range(0, len(locus_dict2[locus])):
                    L = locus_dict2[locus][x]
                    df_hl[L] = df_[list(meta_l[x].columns)].copy()
            else:
                L = locus_dict4[locus]
                df_hl[L] = df_[list(meta_l.columns)].copy()
            df_res_hl = df_hl.copy()
            res_ = defaultdict(list)
            result_dict_hl = defaultdict(dict)
            if collapse:
                for d in df_res_hl:
                    for i in df_hl[d].index:
                        if combine:
                            try:
                                res_[d].append(
                                    '|'.join([l for l in list(dict.fromkeys(df_hl[d].loc[i])) if l == l]))
                            except:
                                res_[d].append('|'.join([str(l) for l in list(
                                    dict.fromkeys(df_hl[d].loc[i])) if l == l]))
                        else:
                            try:
                                res_[d].append(
                                    '|'.join([l for l in list(df_hl[d].loc[i]) if l == l]))
                            except:
                                res_[d].append(
                                    '|'.join([str(l) for l in list(df_hl[d].loc[i]) if l == l]))
                    df_res_hl[d][query] = res_[d]
                    result_dict_hl[d] = dict(df_res_hl[d][query])
                    for k, v in result_dict_hl[d].items():
                        if type(v) is not list:
                            result_dict_hl[d][k] = [v]
                if len(meta_l) == 2 and type(meta_l) is list and type(meta_l) is list:
                    result_dict_ = {query+'_'+H: result_dict_hl[H]}
                    for x in range(0, len(locus_dict2[locus])):
                        L = locus_dict2[locus][x]
                        result_dict_.update({query+'_'+L: result_dict_hl[L]})
                else:
                    result_dict_ = {
                        query+'_heavy': result_dict_hl[H], query+'_light': result_dict_hl[L]}
            else:
                for d in df_res_hl:
                    result_dict_hl[d] = df_res_hl[d]
        else:
            df_res = df_.copy()
            q_res = []
            if collapse:
                for i in metadata_.index:
                    if combine:
                        q_res.append(
                            '|'.join([qq for qq in list(dict.fromkeys(df_.loc[i])) if qq == qq]))
                    else:
                        q_res.append(
                            '|'.join([qq for qq in list(df_.loc[i]) if qq == qq]))
            else:
                for i in metadata_.index:
                    q_res.append([qq for qq in list(df_.loc[i]) if qq == qq])
            df_res[query] = q_res
            result_dict_ = dict(df_res[query])
    else:
        result_dict_ = {x: dict(df_[x]) for x in df_}
    rs_dict1 = {'ig': '[HL]'}
    rs_dict2 = {'ig': 'IG[HKL]'}
    if len(meta_l) == 2 and type(meta_l) is list:
        rs = '_sequence_id_'+rs_dict2[locus]
    else:
        rs = '_sequence_id_'+rs_dict1[locus]
    final_result_ = defaultdict(dict)
    if split:
        if not collapse:
            if len(meta_l) == 2 and type(meta_l) is list:
                names = [k for k in result_dict_hl.keys()]
                final_result = result_dict_hl[names[0]].join(
                    result_dict_hl[names[1]]).join(result_dict_hl[names[2]])
                final_result.columns = [re.sub('_sequence_id', '', q) for q in [
                    query+'_'+str(l) for l in final_result.columns]]
            else:
                try:
                    if type_check(meta_h, 'sequence_id_'+H+'_0'):
                        final_result_h = pd.DataFrame(result_dict_hl[H])
                    else:
                        final_result_h = pd.DataFrame(result_dict_[H])
                except:
                    if type_check(meta_h, 'sequence_id_'+H+'_0'):
                        final_result_h = pd.DataFrame.from_dict(
                            result_dict_hl, orient='index').T
                        final_result_h = final_result_h[meta_h.columns].copy()
                    else:
                        final_result_h = pd.DataFrame.from_dict(
                            result_dict_, orient='index').T
                        final_result_h = final_result_h[meta_h.columns].copy()
                final_result_h.columns = [re.sub(rs, '', q) for q in [
                    query+'_heavy_'+str(l) for l in final_result_h.columns]]
                try:
                    if type_check(meta_h, 'sequence_id_'+H+'_0'):
                        final_result_l = pd.DataFrame(
                            result_dict_hl[locus_dict4[locus]])
                    else:
                        final_result_l = pd.DataFrame(
                            result_dict_[locus_dict4[locus]])
                except:
                    if type_check(meta_h, 'sequence_id_'+H+'_0'):
                        final_result_l = pd.DataFrame.from_dict(
                            result_dict_hl, orient='index').T
                        final_result_l = final_result_l[meta_l.columns].copy()
                    else:
                        final_result_l = pd.DataFrame.from_dict(
                            result_dict_, orient='index').T
                        final_result_l = final_result_l[meta_l.columns].copy()
                final_result_l.columns = [re.sub(rs, '', q) for q in [
                    query+'_light_'+str(l) for l in final_result_l.columns]]
                final_result = final_result_h.join(final_result_l)
        else:
            if len(meta_l) == 2 and type(meta_l) is list:
                if type_check(meta_h, 'sequence_id_'+H+'_0'):
                    for d in result_dict_:
                        final_result_[d] = pd.DataFrame.from_dict(
                            result_dict_[d], orient='index')
                        final_result_[d].columns = [re.sub(rs, '', q) for q in [
                            d+'_'+str(l) for l in final_result_[d].columns]]
                        final_result_[d].columns = [
                            re.sub('_[0-9]', '', q) for q in final_result_[d].columns]
                    names = [k for k in final_result_.keys()]
                    final_result = final_result_[names[0]].join(
                        final_result_[names[1]]).join(final_result_[names[2]])
                else:
                    if verbose:
                        warnings.warn(UserWarning('Query dtype is {}. Ignoring collapse = True.'.format(
                            meta_h['sequence_id_'+H+'_0'].dtype.name)))
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result.columns = [
                        query+re.sub('sequence_id', '', q) for q in final_result.columns]
            else:
                if type_check(meta_h, 'sequence_id_'+H+'_0'):
                    final_result_h = pd.DataFrame.from_dict(
                        result_dict_[query+'_heavy'], orient='index')
                    final_result_h.columns = [query+'_heavy']
                    final_result_l = pd.DataFrame.from_dict(
                        result_dict_[query+'_light'], orient='index')
                    final_result_l.columns = [query+'_light']
                    final_result = final_result_h.join(final_result_l)
                else:
                    if verbose:
                        warnings.warn(UserWarning('Query dtype is {}. Ignoring collapse = True.'.format(
                            meta_h['sequence_id_'+H+'_0'].dtype.name)))
                    final_result_h = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result_h = final_result_h[meta_h.columns].copy()
                    final_result_h.columns = [re.sub(rs, '', q) for q in [
                        query+'_heavy_'+str(l) for l in final_result_h.columns]]
                    final_result_l = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result_l = final_result_l[meta_l.columns].copy()
                    final_result_l.columns = [re.sub(rs, '', q) for q in [
                        query+'_light_'+str(l) for l in final_result_l.columns]]
                    final_result = final_result_h.join(final_result_l)
    else:
        if type_check(meta_h, 'sequence_id_'+H+'_0'):
            if not collapse:
                if len(meta_l) == 2 and type(meta_l) is list:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index')
                    final_result.columns = [re.sub(rs, '', q) for q in [
                        query+'_'+str(l) for l in final_result.columns]]
                else:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index')
                    final_result.columns = [re.sub(rs, '', q) for q in [
                        query+'_'+str(l) for l in final_result.columns]]
            else:
                if len(meta_l) == 2 and type(meta_l) is list:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index')
                    final_result.columns = [query]
                else:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index')
                    final_result.columns = [query]
        else:
            if not collapse:
                if len(meta_l) == 2 and type(meta_l) is list:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result.columns = [re.sub('_sequence_id', '', q) for q in [
                        query+'_'+str(l) for l in final_result.columns]]
                else:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result.columns = [re.sub(rs, '', q) for q in [
                        query+'_'+str(l) for l in final_result.columns]]
            else:
                if verbose:
                    warnings.warn(UserWarning('Query dtype is {}. Ignoring collapse = True and split = False.'.format(
                        meta_h['sequence_id_'+H+'_0'].dtype.name)))
                if len(meta_l) == 2 and type(meta_l) is list:
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result.columns = [re.sub('_sequence_id', '', q) for q in [
                        query+'_'+str(l) for l in final_result.columns]]
                else:
                    typedict = {locus_dict3[locus]: 'heavy',
                                locus_dict4[locus]: 'light'}
                    final_result = pd.DataFrame.from_dict(
                        result_dict_, orient='index').T
                    final_result.columns = [re.sub(rs, '', q) for q in [
                        query+'_'+typedict[l.split('_')[2]]+'_'+l for l in final_result.columns]]

    return(final_result)


def retrieve_result_dict_singular(query, data, meta_h, locus='ig', collapse=True, combine=False, verbose=False):

    df_hl = defaultdict(dict)

    locus_dict1 = {'ig': 'IGH'}
    locus_dict3 = {'ig': 'H'}

    H = locus_dict3[locus]
    if meta_h.shape[1] > 1:
        if collapse:
            newmeta_h = meta_h.copy()
            if type_check(meta_h, 'sequence_id_'+H+'_0'):
                newh = []
                for i in meta_h.index:
                    try:
                        newh.append(
                            '|'.join([h for h in list(dict.fromkeys(newmeta_h.loc[i])) if h == h]))
                    except:
                        newh.append('|'.join([str(h) for h in list(
                            dict.fromkeys(newmeta_h.loc[i])) if h == h]))
                newmeta_h['sequence_id_'+H+'_0'] = newh
                meta_h = pd.DataFrame(newmeta_h['sequence_id_'+H+'_0'].copy())
            else:
                collapse = False
                if verbose:
                    warnings.warn(UserWarning(
                        'Multiple heavy chain contigs mapping to the same cell barcode and/or query dtype is {}. Ignoring collapse = True.'.format(meta_h['sequence_id_'+H+'_0'].dtype.name)))

    metadata_ = meta_h.copy()

    df_ = metadata_.copy()
    if type_check(meta_h, 'sequence_id_'+H+'_0'):
        df_res = df_.copy()
        q_res = []
        if collapse:
            for i in metadata_.index:
                if combine:
                    try:
                        q_res.append(
                            '|'.join([qq for qq in list(dict.fromkeys(df_.loc[i])) if qq == qq]))
                    except:
                        q_res.append('|'.join([str(qq) for qq in list(
                            dict.fromkeys(df_.loc[i])) if qq == qq]))
                else:
                    try:
                        q_res.append(
                            '|'.join([qq for qq in list(df_.loc[i]) if qq == qq]))
                    except:
                        q_res.append(
                            '|'.join([str(qq) for qq in list(df_.loc[i]) if qq == qq]))
        else:
            for i in metadata_.index:
                q_res.append([qq for qq in list(df_.loc[i]) if qq == qq])
        df_res[query] = q_res
        result_dict_ = dict(df_res[query])
    else:
        result_dict_ = {x: dict(df_[x]) for x in df_}

    rs_dict1 = {'ig': '[H]'}
    rs = '_sequence_id_'+rs_dict1[locus]
    final_result_ = defaultdict(dict)

    if type_check(meta_h, 'sequence_id_'+H+'_0'):
        if not collapse:
            final_result = pd.DataFrame.from_dict(result_dict_, orient='index')
            final_result.columns = [re.sub(rs, '', q) for q in [
                query+'_'+str(l) for l in final_result.columns]]
        else:
            final_result = pd.DataFrame.from_dict(result_dict_, orient='index')
            final_result.columns = [query]
    else:
        if not collapse:
            final_result = pd.DataFrame.from_dict(
                result_dict_, orient='index').T
            final_result.columns = [re.sub(rs, '', q) for q in [
                query+'_'+str(l) for l in final_result.columns]]
        else:
            if verbose:
                warnings.warn(UserWarning('Query dtype is {}. Ignoring collapse = True and split = False.'.format(
                    meta_h['sequence_id_'+H+'_0'].dtype.name)))
            typedict = {locus_dict3[locus]: 'heavy'}
            final_result = pd.DataFrame.from_dict(
                result_dict_, orient='index').T
            final_result.columns = [re.sub(rs, '', q) for q in [
                query+'_'+typedict[l.split('_')[2]]+'_'+l for l in final_result.columns]]
    return(final_result)


def initialize_metadata(self, cols, locus_, clonekey, collapse_alleles, verbose):
    init_dict = {}
    for col in cols:
        init_dict.update({col: {'split': True, 'collapse': True,
                                'combine': False, 'locus': locus_, 'split_locus': False}})
    if clonekey in init_dict:
        init_dict.update({clonekey: {'split': False, 'collapse': True,
                                     'combine': True, 'locus': locus_, 'split_locus': False}})
    if 'sample_id' in init_dict:
        init_dict.update({'sample_id': {'split': False, 'collapse': True,
                                        'combine': True, 'locus': locus_, 'split_locus': False}})
    meta_ = defaultdict(dict)
    for k, v in init_dict.items():
        meta_[k] = retrieve_metadata(self.data, query=k, verbose=verbose, **v)
    tmp_metadata = pd.concat(meta_.values(), axis=1, join="inner")

    if 'locus_heavy' in tmp_metadata:
        suffix_h = '_heavy'
        suffix_l = '_light'
    else:
        suffix_h = ''
        suffix_l = ''

    if clonekey in init_dict:
        tmp = tmp_metadata[str(clonekey)].str.split('|', expand=True).stack()
        tmp = tmp.reset_index(drop=False)
        tmp.columns = ['cell_id', 'tmp', str(clonekey)]
        clone_size = tmp[str(clonekey)].value_counts()
        clonesize_dict = dict(clone_size)
        size_of_clone = pd.DataFrame.from_dict(clonesize_dict, orient='index')
        size_of_clone.reset_index(drop=False, inplace=True)
        size_of_clone.columns = [str(clonekey), 'clone_size']
        size_of_clone[str(clonekey)+'_by_size'] = size_of_clone.index+1
        size_dict = dict(
            zip(size_of_clone['clone_id'], size_of_clone['clone_id_by_size']))
        tmp_metadata[str(clonekey)+'_by_size'] = ['|'.join([str(size_dict[c_]) for c_ in c.split('|')])
                                                  if len(c.split('|')) > 1 else str(size_dict[c]) for c in tmp_metadata[str(clonekey)]]
        tmp_metadata[str(
            clonekey)+'_by_size'] = tmp_metadata[str(clonekey)+'_by_size'].astype('category')
        tmp_metadata = tmp_metadata[[str(clonekey), str(clonekey)+'_by_size'] + [
            cl for cl in tmp_metadata if cl not in [str(clonekey), str(clonekey)+'_by_size']]]

    for i in tmp_metadata.index:
        if tmp_metadata.loc[i, 'locus'+suffix_h] == tmp_metadata.loc[i, 'locus'+suffix_h]:
            if not pd.isnull(tmp_metadata.loc[i, 'locus'+suffix_l]):
                if tmp_metadata.loc[i, 'locus'+suffix_l] != '':
                    tmp_metadata.at[i, 'status'] = tmp_metadata.loc[i,
                                                                    'locus'+suffix_h]+' + ' + tmp_metadata.loc[i, 'locus'+suffix_l]
                else:
                    tmp_metadata.at[i, 'status'] = tmp_metadata.loc[i,
                                                                    'locus'+suffix_h] + '_only'
            elif tmp_metadata.loc[i, 'locus'+suffix_h] != '':
                tmp_metadata.at[i, 'status'] = tmp_metadata.loc[i,
                                                                'locus'+suffix_h] + '_only'
            else:
                tmp_metadata.at[i, 'status'] = 'unassigned'
        else:
            tmp_metadata.at[i, 'status'] = 'unassigned'
    tmp_metadata['status_summary'] = [
        'Multi' if '|' in i else i for i in tmp_metadata['status']]

    for i in tmp_metadata.index:
        if tmp_metadata.loc[i, 'productive'+suffix_h] == tmp_metadata.loc[i, 'productive'+suffix_h]:
            if not pd.isnull(tmp_metadata.loc[i, 'productive'+suffix_l]):
                if tmp_metadata.loc[i, 'productive'+suffix_l] != '':
                    tmp_metadata.at[i, 'productive'] = tmp_metadata.loc[i,
                                                                        'productive'+suffix_h]+' + ' + tmp_metadata.loc[i, 'productive'+suffix_l]
                else:
                    tmp_metadata.at[i, 'productive'] = tmp_metadata.loc[i,
                                                                        'productive'+suffix_h]
            elif tmp_metadata.loc[i, 'productive'+suffix_h] != '':
                tmp_metadata.at[i, 'productive'] = tmp_metadata.loc[i,
                                                                    'productive'+suffix_h]
            else:
                tmp_metadata.at[i, 'productive'] = 'unassigned'
        else:
            tmp_metadata.at[i, 'productive'] = 'unassigned'
    tmp_metadata['productive_summary'] = [
        'Multi' if '|' in i else i for i in tmp_metadata['productive']]

    conversion_dict = {'igha1': 'IgA', 'igha2': 'IgA', 'ighm': 'IgM', 'ighd': 'IgD', 'ighe': 'IgE', 'ighg1': 'IgG', 'ighg2': 'IgG', 'ighg3': 'IgG', 'ighg4': 'IgG', 'igkc': 'IgK', 'iglc1': 'IgL', 'iglc2': 'IgL', 'iglc3': 'IgL', 'iglc4': 'IgL', 'iglc5': 'IgL', 'iglc6': 'IgL', 'iglc7': 'IgL',
                       'igha': 'IgA', 'ighg': 'IgG', 'iglc': 'IgL', 'nan': 'unassigned', 'na': 'unassigned', 'NA': 'unassigned', 'None': 'unassigned', '': 'unassigned', 'unassigned': 'unassigned', np.nan: 'unassigned', None: 'unassigned'}  # the key for IgG being igh is on purpose because of how the counter works
    isotype = []
    for k in tmp_metadata['c_call'+suffix_h]:
        if k == k:
            if ',' in k:
                k = '|'.join(k.split(','))
            if '|' in k:
                isotype.append('|'.join([str(z) for z in [conversion_dict[y.lower()] for y in set(
                    [re.sub('[0-9]', '', x) for x in k.split('|')])]]))
            else:
                isotype.append(conversion_dict[k.lower()])
        else:
            isotype.append(k)
    tmp_metadata['isotype'] = isotype
    tmp_metadata['isotype_summary'] = [
        'Multi' if '|' in i else i for i in tmp_metadata['isotype']]

    vdj_gene_calls = ['v_call', 'd_call', 'j_call']
    if collapse_alleles:
        for x in vdj_gene_calls:
            if x in self.data:
                for c in tmp_metadata:
                    if x in c:
                        tmp_metadata[c] = ['|'.join(['|'.join(list(set(yy.split(',')))) for yy in list(set(
                            [re.sub('[*][0-9][0-9]', '', tx) for tx in t.split('|')]))]) for t in tmp_metadata[c]]
    multi = {}
    for i in tmp_metadata.index:
        try:
            if 'v_call_genotyped' in cols:
                hv_ = tmp_metadata.at[i,
                                      'v_call_genotyped'+suffix_h].split('|')
            else:
                hv_ = tmp_metadata.at[i, 'v_call'+suffix_h].split('|')
        except:
            if 'v_call_genotyped' in cols:
                hv_ = tmp_metadata.at[i, 'v_call_genotyped'+suffix_h]
            else:
                hv_ = tmp_metadata.at[i, 'v_call'+suffix_h]
        try:
            hj_ = tmp_metadata.at[i, 'j_call'+suffix_h].split('|')
        except:
            hj_ = tmp_metadata.at[i, 'j_call'+suffix_h]
        try:
            if 'v_call_genotyped' in cols:
                lv_ = tmp_metadata.at[i,
                                      'v_call_genotyped'+suffix_l].split('|')
            else:
                lv_ = tmp_metadata.at[i, 'v_call'+suffix_l].split('|')
        except:
            if 'v_call_genotyped' in cols:
                lv_ = tmp_metadata.at[i, 'v_call_genotyped'+suffix_l]
            else:
                lv_ = tmp_metadata.at[i, 'v_call'+suffix_l]
        try:
            lj_ = tmp_metadata.at[i, 'j_call'+suffix_l].split('|')
        except:
            lj_ = tmp_metadata.at[i, 'j_call'+suffix_l]
        multi_h = []
        multi_l = []
        if len(hv_) > 1:
            multi_h.append(['Multi'+suffix_h+'_v'])
        if len(hj_) > 1:
            multi_h.append(['Multi'+suffix_h+'_j'])
        if len(lv_) > 1:
            multi_l.append(['Multi_light_v'])
        if len(lj_) > 1:
            multi_l.append(['Multi_light_j'])
        if len(multi_h) < 1:
            multi_h.append(['Single'])
        if len(multi_l) < 1:
            multi_l.append(['Single'])
        multih = '|'.join(list(set(flatten(multi_h))))
        multil = '|'.join(list(set(flatten(multi_l))))
        if len(multih) > 0:
            if len(multil) > 0:
                multi[i] = multih + ' + ' + multil
            else:
                multi[i] = multih
        else:
            multi[i] = 'unassigned'
    tmp_metadata['vdj_status_detail'] = pd.Series(multi)
    tmp_metadata['vdj_status'] = ['Multi' if bool(re.search(
        'Multi'+suffix_h+'(.*)Multi'+suffix_l, i)) else 'Multi' if '|' in i else 'Single' for i in tmp_metadata['vdj_status_detail']]

    self.metadata = tmp_metadata.copy()


def update_metadata(self, retrieve=None, locus=None, clone_key=None, split=True, collapse=True, combine=True, split_locus=False, collapse_alleles=True, reinitialize=False,  verbose=False):
    """
    A `Dandelion` initialisation function to update and populate the `.metadata` slot.

    Parameters
    ----------
    self : Dandelion
        `Dandelion` object.
    retrieve : str, sequence, list, optional
        Column name in `.data` slot to retrieve and update the metadata.
    locus : str, optional
        Mode for creating metadata. None defaults to 'ig'. Currently only accepts 'ig'.
    clone_key : str, optional
        Column name of clone id. None defaults to 'clone_id'.
    split : bool
        Only applies if retrieve option is not None. Returns the retrieval splitted into two columns, e.g. one for heavy and one for light chains in BCR data, if True. Interacts with collapse, combine and split_locus options.
    collapse : bool
        Only applies if retrieve option is not None. Returns the retrieval as a collapsed entry if multiple entries are found (e.g. v genes from multiple contigs) where each entry will be separated by a '|' if True. Interacts with split, combine and split_locus options.
    combine : bool
        Only applies if retrieve option is not None. Returns the retrieval as a collapsed entry with only unique entries (separated by a '|' if multiple are found). Interacts with split, collapse, and split_locus options.
    split_locus : bool
        Only applies if retrieve option is not None. Similar to split except it returns the retrieval splitted into multiple columns corresponding to each unique element in the 'locus' column (e.g. IGH, IGK, IGL). Interacts with split, collapse, and combine options.
    collapse_alleles : bool
        Returns the V-D-J genes with allelic calls if False.
    reinitialize : bool
        Whether or not to reinitialize the current metadata. Useful when updating older versions of `dandelion` to newer version.
    verbose : bool
        Whether or not to print warning messages when constructing object.
    Returns
    -------
    `Dandelion` object with `.metadata` slot initialized.
    """

    if locus is None:
        locus_ = 'ig'
    else:
        locus_ = locus

    if clone_key is None:
        clonekey = 'clone_id'
    else:
        clonekey = clone_key

    cols = ['sequence_id', 'cell_id', 'locus', 'productive',
            'v_call', 'j_call', 'c_call', 'umi_count', 'junction_aa']

    if 'umi_count' not in self.data:
        cols = list(map(lambda x: 'duplicate_count' if x ==
                        'umi_count' else x, cols))
        if 'duplicate_count' not in self.data:
            raise ValueError(
                "Unable to initialize metadata due to missing keys. Please ensure either 'umi_count' or 'duplicate_count' is in the input data.")

    if not all([c in self.data for c in cols]):
        raise ValueError(
            'Unable to initialize metadata due to missing keys. Please ensure the input data contains all the following columns: {}'.format(cols))

    if 'sample_id' in self.data:
        cols = ['sample_id'] + cols

    if 'v_call_genotyped' in self.data:
        cols = list(
            map(lambda x: 'v_call_genotyped' if x == 'v_call' else x, cols))

    for c in ['sequence_id', 'cell_id']:
        cols.remove(c)

    if clonekey in self.data:
        if not all(pd.isnull(self.data['clone_id'])):
            cols = [clonekey] + cols

    metadata_status = self.metadata
    if (metadata_status is None) or reinitialize:
        initialize_metadata(self, cols, locus_, clonekey,
                            collapse_alleles, verbose)

    tmp_metadata = self.metadata.copy()

    if retrieve is not None:
        ret_dict = {}
        if type(retrieve) is str:
            retrieve = [retrieve]
        for ret in retrieve:
            ret_dict.update({ret: {'split': split, 'collapse': collapse,
                                   'combine': combine, 'locus': locus_, 'split_locus': split_locus}})

        vdj_gene_ret = ['v_call', 'd_call', 'j_call']

        retrieve_ = defaultdict(dict)
        for k, v in ret_dict.items():
            if k in self.data.columns:
                retrieve_[k] = retrieve_metadata(
                    self.data, query=k, verbose=verbose, **v)
            else:
                raise KeyError(
                    'Cannot retrieve \'%s\' : Unknown column name.' % k)
        ret_metadata = pd.concat(retrieve_.values(), axis=1, join="inner")

        if collapse_alleles:
            for k in ret_dict.keys():
                if k in vdj_gene_ret:
                    for c in ret_metadata:
                        if k in c:
                            ret_metadata[c] = ['|'.join(['|'.join(list(set(yy.split(',')))) for yy in list(set(
                                [re.sub('[*][0-9][0-9]', '', tx) for tx in t.split('|')]))]) for t in ret_metadata[c]]

        for r in ret_metadata:
            tmp_metadata[r] = pd.Series(ret_metadata[r])
        self.metadata = tmp_metadata.copy()


class Dandelion:
    """
    `Dandelion` class object.

    Main class object storing input/ouput slots for all functions.

    """

    def __init__(self, data=None, metadata=None, germline=None, distance=None, edges=None, layout=None, graph=None, initialize=True, **kwargs):
        self.data = data
        self.metadata = metadata
        self.distance = distance
        self.edges = edges
        self.layout = layout
        self.graph = graph
        self.threshold = None
        self.germline = {}

        if germline is not None:
            self.germline.update(germline)

        if os.path.isfile(str(self.data)):
            self.data = load_data(self.data)

        if self.data is not None:
            self.n_contigs = self.data.shape[0]
            if metadata is None:
                if initialize is True:
                    update_metadata(self, **kwargs)
                try:
                    self.n_obs = self.metadata.shape[0]
                except:
                    self.n_obs = 0
            else:
                self.metadata = metadata
                self.n_obs = self.metadata.shape[0]
        else:
            self.n_contigs = 0
            self.n_obs = 0

    def _gen_repr(self, n_obs, n_contigs) -> str:
        # inspire by AnnData's function
        descr = f"Dandelion class object with n_obs = {n_obs} and n_contigs = {n_contigs}"
        for attr in ["data", "metadata", "distance", "edges"]:
            try:
                keys = getattr(self, attr).keys()
            except:
                keys = []
            if len(keys) > 0:
                descr += f"\n    {attr}: {str(list(keys))[1:-1]}"
            else:
                descr += f"\n    {attr}: {str(None)}"
        if self.layout is not None:
            descr += f"\n    layout: {', '.join(['layout for '+ str(len(x)) + ' vertices' for x in (self.layout[0], self.layout[1])])}"
        else:
            descr += f"\n    layout: {str(None)}"
        if self.graph is not None:
            descr += f"\n    graph: {', '.join(['networkx graph of '+ str(len(x)) + ' vertices' for x in (self.graph[0], self.graph[1])])} "
        else:
            descr += f"\n    graph: {str(None)}"
        return descr

    def __repr__(self) -> str:
        # inspire by AnnData's function
        return self._gen_repr(self.n_obs, self.n_contigs)

    def copy(self):
        """
        Performs a deep copy of all slots in `Dandelion` class.

        Parameters
        ----------
        self : Dandelion
            `Dandelion` object.

        Returns
        -------
        a deep copy of `Dandelion` class.
        """
        return copy.deepcopy(self)

    def update_germline(self, corrected=None, germline=None, org='human'):
        """
        Update germline reference with corrected sequences and store in `Dandelion` object.

        Parameters
        ----------
        self : Dandelion
            `Dandelion` object.
        corrected : dict, str, optional
            dictionary of corrected germline sequences or file path to corrected germline sequences fasta file.
        germline : str, optional
            path to germline database folder. Defaults to `$GERMLINE` environmental variable.
        org : str
            organism of reference folder. Default is 'human'.

        Returns
        -------
        updated germline reference diciontary in `.germline` slot.
        """
        start = logg.info('Updating germline reference')
        env = os.environ.copy()
        if germline is None:
            try:
                gml = env['GERMLINE']
            except:
                raise OSError(
                    'Environmental variable GERMLINE must be set. Otherwise, please provide path to folder containing germline IGHV, IGHD, and IGHJ fasta files.')
            gml = gml+'imgt/'+org+'/vdj/'
        else:
            if os.path.isdir(germline):
                gml = germline
            elif type(germline) is not list:
                germline_ = [germline]
                if len(germline_) < 3:
                    raise OSError('Input for germline is incorrect. Please provide path to folder containing germline IGHV, IGHD, and IGHJ fasta files, or individual paths to the germline IGHV, IGHD, and IGHJ fasta files (with .fasta extension) as a list.')
                else:
                    gml = []
                    for x in germline_:
                        if not x.endswith('.fasta'):
                            raise OSError(
                                'Input for germline is incorrect. Please provide path to folder containing germline IGHV, IGHD, and IGHJ fasta files, or individual paths to the germline IGHV, IGHD, and IGHJ fasta files (with .fasta extension) as a list.')
                        gml.append(x)
            elif type(germline) is list:
                if len(germline) < 3:
                    raise OSError('Input for germline is incorrect. Please provide path to folder containing germline IGHV, IGHD, and IGHJ fasta files, or individual paths to the germline IGHV, IGHD, and IGHJ fasta files (with .fasta extension) as a list.')
                else:
                    gml = []
                    for x in germline:
                        if not x.endswith('.fasta'):
                            raise OSError(
                                'Input for germline is incorrect. Please provide path to folder containing germline IGHV, IGHD, and IGHJ fasta files, or individual paths to the germline IGHV, IGHD, and IGHJ fasta files (with .fasta extension) as a list.')
                        gml.append(x)

        if type(gml) is not list:
            gml = [gml]

        germline_ref = readGermlines(gml)
        if corrected is not None:
            if type(corrected) is dict:
                personalized_ref_dict = corrected
            elif os.path.isfile(str(corrected)):
                personalized_ref_dict = readGermlines([corrected])
            # update with the personalized germline database
            if 'personalized_ref_dict' in locals():
                germline_ref.update(personalized_ref_dict)
            else:
                raise OSError(
                    'Input for corrected germline fasta is incorrect. Please provide path to file containing corrected germline fasta sequences.')

        self.germline.update(germline_ref)
        logg.info(' finished', time=start,
                  deep=('Updated Dandelion object: \n'
                        '   \'germline\', updated germline reference\n'))

    def write_pkl(self, filename='dandelion_data.pkl.pbz2', **kwargs):
        """
        Writes a `Dandelion` class to .pkl format.

        Parameters
        ----------
        filename
            path to `.pkl` file.
        **kwargs
            passed to `_pickle`.
        """
        if isBZIP(filename):
            try:
                with bz2.BZ2File(filename, 'wb') as f:
                    cPickle.dump(self, f, **kwargs)
            except:
                with bz2.BZ2File(filename, 'wb') as f:
                    cPickle.dump(self, f, protocol=4, **kwargs)
        elif isGZIP(filename):
            try:
                with gzip.open(filename, 'wb') as f:
                    cPickle.dump(self, f, **kwargs)
            except:
                with gzip.open(filename, 'wb') as f:
                    cPickle.dump(self, f, protocol=4, **kwargs)
        else:
            f = open(filename, 'wb')
            cPickle.dump(self, f, **kwargs)
            f.close()

    def write_h5(self, filename='dandelion_data.h5', complib=None, compression=None, compression_level=None, **kwargs):
        """
        Writes a `Dandelion` class to .h5 format.

        Parameters
        ----------
        filename
            path to `.h5` file.
        complib : str, optional
            method for compression for data frames. see (https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.to_hdf.html) for more options.
        compression : str, optional
            same call as complib. Just a convenience option.
        compression_opts : {0-9}, optional
            Specifies a compression level for data. A value of 0 disables compression.
        **kwargs
            passed to `pd.DataFrame.to_hdf`.
        """
        if compression_level is None:
            compression_level = 9
        else:
            compression_level = compression_level

        # a little hack to overwrite the existing file?
        with h5py.File(filename,  "w") as hf:
            for datasetname in hf.keys():
                del hf[datasetname]

        if complib is None and compression is None:
            comp = None
        elif complib is not None and compression is None:
            comp = complib
        elif complib is None and compression is not None:
            comp = compression
        if complib is not None and compression is not None:
            raise ValueError(
                'Please specify only complib or compression. They do the same thing.')

        # now to actually saving
        for col in self.data.columns:
            weird = (self.data[[col]].applymap(type) !=
                     self.data[[col]].iloc[0].apply(type)).any(axis=1)
            if len(self.data[weird]) > 0:
                self.data[col] = self.data[col].where(
                    pd.notnull(self.data[col]), '')
        self.data.to_hdf(filename, "data", complib=comp,
                         complevel=compression_level, **kwargs)

        if self.metadata is not None:
            for col in self.metadata.columns:
                weird = (self.metadata[[col]].applymap(
                    type) != self.metadata[[col]].iloc[0].apply(type)).any(axis=1)
                if len(self.metadata[weird]) > 0:
                    self.metadata[col] = self.metadata[col].where(
                        pd.notnull(self.metadata[col]), '')
            self.metadata.to_hdf(filename, "metadata", complib=comp,
                                 complevel=compression_level, format='table', nan_rep=np.nan, **kwargs)
        # except:
        #     warnings.warn("`metadata` slot not saved. Please check if there is incompatible dtypes in the metadata table.")
        #     pass
        try:
            if 'index' in self.edges.columns:
                self.edges.drop('index', axis=1, inplace=True)
            self.edges.to_hdf(filename, "edges", complib=comp,
                              complevel=compression_level, **kwargs)
        except:
            pass

        graph_counter = 0
        try:
            for g in self.graph:
                G = nx.to_pandas_adjacency(g, nonedge=np.nan)
                G.to_hdf(filename, "graph/graph_"+str(graph_counter),
                         complib=comp, complevel=compression_level, **kwargs)
                graph_counter += 1
        except:
            pass

        try:
            for d in self.distance:
                # how to make this faster?
                dat = pd.DataFrame(self.distance[d].toarray())
                dat.to_hdf(filename, "distance/"+d, complib=comp,
                           complevel=compression_level, **kwargs)
        except:
            pass

        with h5py.File(filename,  "a") as hf:
            # try:
            #     for d in self.distance:
            #         hf.create_dataset('distance/'+d+'/data', data=self.distance[d].data, compression = compression, compression_opts = compression_level)
            #         hf.create_dataset('distance/'+d+'/indptr', data=self.distance[d].indptr, compression = compression, compression_opts = compression_level)
            #         hf.create_dataset('distance/'+d+'/indices', data=self.distance[d].indices, compression = compression, compression_opts = compression_level)
            #         hf['distance/'+d].attrs['shape'] = self.distance[d].shape
            # except:
            #     pass

            try:
                layout_counter = 0
                for l in self.layout:
                    try:
                        hf.create_group('layout/layout_'+str(layout_counter))
                    except:
                        pass
                    for k in l.keys():
                        hf['layout/layout_' +
                            str(layout_counter)].attrs[k] = l[k]
                    layout_counter += 1
            except:
                pass

            if len(self.germline) > 0:
                try:
                    hf.create_group('germline')
                except:
                    pass
                for k in self.germline.keys():
                    hf['germline'].attrs[k] = self.germline[k]
            if self.threshold is not None:
                tr = self.threshold
                hf.create_dataset('threshold', data=tr)


def isGZIP(filename):
    if filename.split('.')[-1] == 'gz':
        return True
    return False


def isBZIP(filename):
    if filename.split('.')[-1] == 'pbz2':
        return True
    return False


def read_pkl(filename='dandelion_data.pkl.pbz2'):
    """
    Reads in and returns a `Dandelion` class saved using pickle format.

    Parameters
    ----------
    filename
        path to `.pkl` file. Depending on the extension, it will try to unzip accordingly.

    Returns
    -------
    Dandelion object.
    """
    if isBZIP(filename):
        data = bz2.BZ2File(filename, 'rb')
        data = cPickle.load(data)
    elif isGZIP(filename):
        data = gzip.open(filename, 'rb')
        data = cPickle.load(data)
    else:
        with open(filename, 'rb') as f:
            data = cPickle.load(f)
    return(data)


def read_h5(filename='dandelion_data.h5'):
    """
    Reads in and returns a `Dandelion` class from .h5 format.

    Parameters
    ----------
    filename
        path to `.h5` file

    Returns
    -------
    `Dandelion` object.
    """
    try:
        data = pd.read_hdf(filename, 'data')
    except:
        raise AttributeError(
            '{} does not contain attribute `data`'.format(filename))
    try:
        metadata = pd.read_hdf(filename, 'metadata')
    except:
        pass

    try:
        edges = pd.read_hdf(filename, 'edges')
    except:
        pass

    try:
        g_0 = pd.read_hdf(filename, 'graph/graph_0')
        g_1 = pd.read_hdf(filename, 'graph/graph_1')
        g_0 = g_0 + 1
        g_0 = g_0.fillna(0)
        g_1 = g_1 + 1
        g_1 = g_1.fillna(0)
        graph0 = nx.from_pandas_adjacency(g_0)
        graph1 = nx.from_pandas_adjacency(g_1)
        for u, v, d in graph0.edges(data=True):
            d['weight'] = d['weight']-1
        for u, v, d in graph1.edges(data=True):
            d['weight'] = d['weight']-1
        graph = (graph0, graph1)
    except:
        pass

    with h5py.File(filename, 'r') as hf:
        try:
            layout0 = {}
            for k in hf['layout/layout_0'].attrs.keys():
                layout0.update({k: np.array(hf['layout/layout_0'].attrs[k])})
            layout1 = {}
            for k in hf['layout/layout_1'].attrs.keys():
                layout1.update({k: np.array(hf['layout/layout_1'].attrs[k])})
            layout = (layout0, layout1)
        except:
            pass

        germline = {}
        try:
            for g in hf['germline'].attrs:
                germline.update({g: hf['germline'].attrs[g]})
        except:
            pass

        distance = Tree()
        try:
            for d in hf['distance'].keys():
                d_ = pd.read_hdf(filename, 'distance/'+d)
                distance[d] = scipy.sparse.csr_matrix(d_.values)
                # d_ = hf['distance'][d]
                # distance[d] = scipy.sparse.csr_matrix((d_['data'][:],d_['indices'][:], d_['indptr'][:]), d_.attrs['shape'])
        except:
            pass

        try:
            threshold = np.float(np.array(hf['threshold']))
        except:
            threshold = None

    constructor = {}
    constructor['data'] = data
    if 'metadata' in locals():
        constructor['metadata'] = metadata
    if 'germline' in locals():
        constructor['germline'] = germline
    if 'edges' in locals():
        constructor['edges'] = edges
    if 'distance' in locals():
        constructor['distance'] = distance
    if 'layout' in locals():
        constructor['layout'] = layout
    if 'graph' in locals():
        constructor['graph'] = graph
    try:
        res = Dandelion(**constructor)
    except:
        res = Dandelion(**constructor, initialize=False)

    if 'threshold' in locals():
        res.threshold = threshold
    else:
        pass
    return(res)


def concat(arrays, check_unique=True):
    """
    Concatenate dataframe and return as `Dandelion` object.

    Parameters
    ----------
    arrays : List
        List of `Dandelion` class objects or pandas dataframe
    check_unique : bool
        Check the new index for duplicates. Otherwise defer the check until necessary. Setting to False will improve the performance of this method.

    Returns
    -------
    sample_dict
        dictionary
    """
    arrays = list(arrays)

    try:
        arrays_ = [x.data.copy() for x in arrays]
    except:
        arrays_ = [x.copy() for x in arrays]

    if check_unique:
        try:
            df = pd.concat(arrays_, verify_integrity=True)
        except:
            for i in range(0, len(arrays)):
                arrays_[i]['sequence_id'] = [x + '__' +
                                             str(i) for x in arrays_[i]['sequence_id']]
            arrays_ = [load_data(x) for x in arrays_]
            df = pd.concat(arrays_, verify_integrity=True)
    else:
        df = pd.concat(arrays_)
    try:
        out = Dandelion(df)
    except:
        out = Dandelion(df, initialize=False)
    return(out)


def read_10x_airr(file):
    """
    Reads the 10x AIRR rearrangement .tsv directly and returns a `Dandelion` object.

    Parameters
    ----------
    file
        path to `airr_rearrangement.tsv`
    sample_id : str, optional
        Name to populated sample id column

    Returns
    -------
    `Dandelion` object of pandas data frame.

    """    
    dat = load_data(file)
    # get all the v,d,j,c calls
    if 'locus' not in dat:
        tmp = [(v, d, j, c) for v, d, j, c in zip(
            dat['v_call'], dat['d_call'], dat['j_call'], dat['c_call'])]
        locus = []
        for t in tmp:
            if all('IGH' in x for x in t if x == x):
                locus.append('IGH')
            elif all('IGK' in x for x in t if x == x):
                locus.append('IGK')
            elif all('IGL' in x for x in t if x == x):
                locus.append('IGL')
            else:
                locus.append(np.nan)
        dat['locus'] = locus

    return(Dandelion(dat))


def to_scirpy(Dandelion):
    """
    Converts a `Dandelion` object to scirpy's format.

    Parameters
    ----------
    Dandelion
        `Dandelion` object

    Returns
    -------
    `AnnData` object in the format initialized by `scirpy`.

    """
    try:
        import scirpy as ir
    except:
        raise ImportError('Please install scirpy. pip install scirpy')
    return(ir.io.read_dandelion(Dandelion))


def read_scirpy(adata):
    """
    Reads a scirpy initialized oject and returns a `Dandelion` object.

    Parameters
    ----------
    adata
        scirpy initialized `AnnData` object.

    Returns
    -------
    `Dandelion` object.

    """
    try:
        import scirpy as ir
    except:
        raise ImportError('Please install scirpy. pip install scirpy')
    return(ir.io.to_dandelion(Dandelion))
