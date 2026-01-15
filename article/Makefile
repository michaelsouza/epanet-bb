FIGURES = $(wildcard figures/*)

all: article.pdf

algorithm.sty algorithmic.sty: algorithms.ins algorithms.dtx
	latex -interaction=nonstopmode algorithms.ins

article.pdf: article.tex references.bib algorithm.sty algorithmic.sty $(FIGURES)
	pdflatex article.tex
	bibtex article
	pdflatex article.tex
	pdflatex article.tex

clean:
	rm -f *.aux *.log *.out *.bbl *.blg *.pdf *.bak*
