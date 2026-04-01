TEXFILE := letter_Deletic_WR.tex
PDFFILE := letter_Deletic_WR.pdf
LATEX := pdflatex
LATEXFLAGS := -interaction=nonstopmode -halt-on-error -file-line-error
BUILDDIR := .

.PHONY: all clean

all: $(PDFFILE)

$(PDFFILE): $(TEXFILE)
	$(LATEX) $(LATEXFLAGS) -output-directory=$(BUILDDIR) $(TEXFILE)

clean:
	rm -f $(PDFFILE) *.aux *.log *.out *.fdb_latexmk *.fls *.synctex.gz

