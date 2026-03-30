PAPER := paper

.PHONY: all clean watch

all:
	latexmk -pdf -bibtex -interaction=nonstopmode $(PAPER).tex

watch:
	latexmk -pdf -bibtex -pvc -view=none -interaction=nonstopmode $(PAPER).tex

clean:
	latexmk -C $(PAPER).tex
	rm -f $(PAPER).fff $(PAPER).ttt
