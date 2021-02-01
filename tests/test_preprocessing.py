#!/usr/bin/env python
# basic requirements for test data
import sys
import os
import dandelion as ddl
import scanpy as sc
import pandas as pd
import requests
from io import StringIO
import warnings


def test_setup_preprocessing():
    file1 = "https://cf.10xgenomics.com/samples/cell-vdj/5.0.0/sc5p_v2_hs_B_1k_multi_5gex_b/sc5p_v2_hs_B_1k_multi_5gex_b_vdj_b_filtered_contig.fasta"
    file2 = "https://cf.10xgenomics.com/samples/cell-vdj/5.0.0/sc5p_v2_hs_B_1k_multi_5gex_b/sc5p_v2_hs_B_1k_multi_5gex_b_vdj_b_filtered_contig_annotations.csv"
    r1 = requests.get(file1)
    open("tests/filtered_contig.fasta", "wb").write(r1.content)
    r2 = requests.get(file2)
    open("tests/filtered_contig_annotations.csv", "wb").write(r2.content)


def test_format_headers():
    samples = ["tests"]
    ddl.pp.format_fastas(samples, prefix="tests")


def test_reannotate():
    samples = ["tests"]
    ddl.pp.reannotate_genes(samples, igblast_db = "database/igblast/", germline = "database/germlines/imgt/human/vdj/")


def test_reassign():
    samples = ["tests"]
    ddl.pp.reassign_alleles(samples, combined_folder="tests", germline = "database/germlines/imgt/human/vdj/")


def test_assign_isotype():
    samples = ["tests"]
    ddl.pp.assign_isotypes(samples, blastdb = "database/blast/", plot=False)


def test_quantify_mut():
    filePath = "tests/dandelion/data/test_filtered_contig_igblast_db-pass_genotyped.tsv"
    ddl.pp.quantify_mutations(filePath)


def test_scanpy():
    scfile = "https://cf.10xgenomics.com/samples/cell-vdj/5.0.0/sc5p_v2_hs_B_1k_multi_5gex_b/sc5p_v2_hs_B_1k_multi_5gex_b_count_filtered_feature_bc_matrix.h5"
    r = requests.get(scfile)
    open("tests/sctest2.h5", "wb").write(r.content)
    adata = sc.read_10x_h5("tests/sctest2.h5")    
    adata.write("tests/sctest2.h5ad", compression="gzip")
    print(adata)


def test_filter():
    adata = sc.read_10x_h5("tests/sctest2.h5")
    bcr = pd.read_csv("tests/dandelion/data/test_filtered_contig_igblast_db-pass_genotyped.tsv", sep="\t")
    bcr.reset_index(inplace=True, drop=True)
    adata.obs["filter_rna"] = False
    vdj, adata = ddl.pp.filter_bcr(bcr, adata)
    adata.write("tests/sctest2.h5ad", compression="gzip")
    vdj.write_h5("tests/test2.h5", compression="bzip2")


def test_update_metadata():
    test = ddl.read_h5("tests/test2.h5")
    ddl.update_metadata(test, "sequence_id")


def test_find_clones():
    test = ddl.read_h5("tests/test2.h5")
    ddl.tl.find_clones(test)


def test_generate_network():
    test = ddl.read_h5("tests/test2.h5")
    ddl.tl.generate_network(test)


def test_downsampling():
    test = ddl.read_h5("tests/test2.h5")
    ddl.tl.generate_network(test)
    test_downsample = ddl.tl.generate_network(test, downsample=100)
    print(test_downsample)


def test_transfer():
    test = ddl.read_h5("tests/test2.h5")
    adata = sc.read_h5ad("tests/sctest2.h5ad")
    sc.pp.filter_cells(adata, min_genes=200)
    sc.pp.filter_genes(adata, min_cells=3)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, min_mean=0.0125, max_mean=3, min_disp=0.5)
    adata = adata[:, adata.var["highly_variable"]].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, svd_solver="arpack")
    sc.pp.neighbors(adata)
    ddl.tl.transfer(adata, test)
    adata.write("tests/sctest2.h5ad", compression="gzip")


if __name__ == "__main__":
    test_setup_preprocessing()
    test_format_headers()
    test_reannotate()
    test_reassign()
    test_assign_isotype()
    test_quantify_mut()
    test_scanpy()
    test_filter()
    test_update_metadata()
    test_find_clones()
    test_generate_network()
    test_downsampling()
    test_transfer()
