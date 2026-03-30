PAPER := paper

.PHONY: all clean watch

all:
	latexmk -pdf -bibtex -f -interaction=nonstopmode $(PAPER).tex

watch:
	latexmk -pdf -bibtex -pvc -view=none -f -interaction=nonstopmode $(PAPER).tex

clean:
	latexmk -C $(PAPER).tex
	rm -f $(PAPER).fff $(PAPER).ttt $(PAPER).fdb_latexmk $(PAPER).fls
