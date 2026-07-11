---
title: "DevFlows fixture paper: a minimal Open Journals build"
tags:
  - Python
  - reproducibility
  - testing
authors:
  - given-names: Ada
    surname: Fixture
    orcid: 0000-0000-0000-0001
    affiliation: 1
affiliations:
  - name: DevFlows Test Lab
    index: 1
date: 10 July 2026
bibliography: paper.bib
---

# Summary

This is a minimal fixture paper used by the DevFlows `paper-openjournals`
reusable workflow scenarios to exercise the `openjournals/inara` container end
to end. It carries just enough Open Journals front-matter to produce a
`CITATION.cff` and a JATS document without compiling any LaTeX, which keeps the
hosted success scenarios fast.

# Statement of need

The `paper-openjournals` workflow builds Open Journals papers (JOSS, JOSE, and
ReScience C) reproducibly from a Markdown source, pinning the inara image by tag
and passing every input through a DevFlows script rather than interpolating it
into a shell command [@knuth1984].

# Acknowledgements

We acknowledge the Open Journals project for the inara tooling.

# References
