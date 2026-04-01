Submitting Your Manuscript
Manuscripts must be submitted through the journal's Editorial Manager website. Links to the submission page can be found on the journal home page in the ASCE Library. ASCE will not review any manuscripts sent via email or mail.

LaTeX User Guide for Editorial Manager
The purpose of this section is to provide helpful information in uploading LaTeX manuscripts to Editorial Manager for ASCE Journals. Users of this document should consider submitting additional tips or directions that will assist LaTeX users. ASCE encourages authors to use the Overleaf template for preparing LaTeX files. The platform and use of the template are free.

Authors have two options when submitting LaTeX manuscripts:

Submit a PDF manuscript as an initial submission and then build the PDF in Editorial Manager at the revision stage, using the main .tex file and all the supporting files. Going this route requires that the author submit all LaTeX files as “manuscript” files. A PDF is produced in Editorial Manager. All ASCE's regular formatting and figure guidelines apply. This is the process that ASCE has used for many years.
Submit a PDF document as the manuscript file at *both* new and revised submission stages. If an author opts for this, the author MUST use Overleaf to produce that PDF. The author is NOT allowed to use a compiler on their own machine.
The steps (and troubleshooting) for both these options are outlined in the following section.

Building the PDF in Editorial Manager
First and foremost, all LaTeX files must be submitted as “Manuscript” files. Style files and auxiliary .bbl file (if using BibTeX) are all part of the manuscript.

The generated PDF should be carefully reviewed for error messages that may indicate the exact problem (e.g., missing style files or figures in the wrong format).

Question marks in the references of the PDF most likely mean that the .tex file(s) are in subdirectories. All associated files must be in one directory for the submission to build.

The Comprehensive TeX Archive Network (CTAN) website provides an “ascelike” style file template for authors to use on their local computer. The Editorial Manager system also contains the “ascelike” style file, so users do not have to upload it with their submissions. If not using “ascelike,” authors will need to upload the style files, as previously described. In addition, ASCE has partnered with Overleaf for a template that has been built and tested for maximum interoperability with Editorial Manager.

Bibliography management should be done through BibTeX; ASCE has not verified if the .bst provided as part of the “ascelike” template is compatible with BibLaTeX. When using BibTeX, authors must upload the auxiliary .bbl file (not the .bib file of references) as a “Manuscript” file.

Figures or images should not be added to the document itself. Images must be uploaded into Editorial Manager as separate files (figures) in BMP, EPS, PDF, PS, or TIF/TIFF formats. They will automatically be placed at the end of the manuscript, which is where they will need to be after acceptance.

Large or cutoff images need to be resized to fit on one 8.5 × 11 in. page. When there is a problem caused by not resizing PostScript files (the images are cut off), the author will either need to resize the images or save the files in a format that Editorial Manager can recognize as an image. Please note that EPS files are the best choice for image files in LaTeX submissions.

The “amsmath” package, included in the MiKTeX installation, is an acceptable extension to Math Mode.

Captions should not be introduced using the “subcaption” package. Continuous line numbering is required for all manuscript submissions.

To do this in LaTeX, authors should use the “lineno” package. Documentation for this can be found on the Comprehensive TeX Archive Network (CTAN) website. NOTE: The “lineno” package does not work well with the “ascelike” package unless equation environments are wrapped with {linenomath*}.

For example:

\begin{linenomath*}    

\begin{equation}    

y = ax + b    

\end{equation}

\end{linenomath*}

LaTeX Revision Process I: Building the PDF from TeX files in Editorial Manager
The most common error when building a PDF in Editorial Manager out of LaTeX source files is that authors upload their .bst, .cls, .bib, .bbl as Supplemental files. They must be uploaded as “Manuscript” files in order to successfully build a PDF in the system.
Figures, Response to Reviewers Comments, and other files should be uploaded as their relevant submission item (i.e., a figure is uploaded as the “figure” file type).
All ASCE's revision guidelines apply. Figures must be uploaded as separate files, line numbering is required, and Response to Reviewer Comments is required, among others.
Other Tips if the Resulting PDF produces errors
If using BibTeX, you will need to upload the auxiliary .bbl file (not the .bib file of references) as a “Manuscript” file.
All figures must be included in EPS or PDF format. Other formats will not build properly. If using PDF figures with the \includegraphics command, authors must use the .pdf extension (i.e., \includegraphics{alld.pdf} instead of \includegraphics{alld}).
If the Editorial Manager PDF does not build properly, check the PDF for error messages. This will often lead to the problem (i.e., missing style files or figures in the wrong format).
Images cannot be referenced in subfolders. Make sure accompanying files are referenced correctly in the .tex file.
An example of a correctly referenced image: \epsfig{figure=alld.eps,width=.5\textwidth}.
An example of an incorrectly referenced image: \epsfig{figure=images/alld.eps,width=.5\textwidth}.
If question marks are present in the references of the PDF, most likely the .tex file(s) are in subdirectories. TeX submissions cannot include subdirectories for the submission to properly build. All associated files must be in one directory for the submission to build.
For large or cutoff images, resize the image to fit on one 8.5 x 11 in. page.
LaTeX Revision Process II: Submitting an Overleaf PDF
To submit a PDF at the revision stage, authors must use the ASCE Overleaf Template to create their PDF.
Authors must include their name in the date stamp in the document preamble so that a date stamp is produced in the resulting PDF. ASCE will check that the date stamp matches the submission date in Editorial Manager on every revision. There cannot be a date stamp of 01/01/2022 and a submission date of 03/01/2022. There is no other way for ASCE to verify that the LaTeX source files match the PDF that is being uploaded, and they absolutely must match. The paper will be sent back for correction if the dates do not match.
Date Stamp on the PDF: There must be no compile errors in the Overleaf system. Compile errors must be fixed before the resulting PDF is submitted to ASCE. For questions about compile errors in Overleaf, please contact ASCE staff.
Once all errors are corrected and the PDF meets ASCE submission guidelines, the author must download the Overleaf PDF and the LaTeX submission files (these will download in a Zip file).
Click on “Project.”
Click on “Download as Zip” under the files.
Click on “PDF” to download the PDF.
Upload the PDF as a “Manuscript” file in Editorial Manager.
Upload the .tex, .cls, .bst, .bib (and/or .bbl) as “Overleaf Companions to PDF” files in Editorial Manager. These files will not build into the PDF. They will be available to the Production Department if needed. Every revision must include a date-stamped PDF, a LaTeX file with a matching “modified” date, and a matching submission date. The paper will be sent back to the author if these three dates do not match.
Figures in JPEG or TIFF format are not allowed in this process. Figures must be submitted as EPS, PS, or PDF.
Figures, Response to Reviewer Comments, and other files are uploaded as their relevant submission item (i.e., a figure as a figure).
All ASCE's revision guidelines apply. Figures must be uploaded as separate files, line numbering is required, a Response to Reviewer Comments is required, and so on.
For additional help with LaTeX, please visit the following resources
Overleaf — A collaborative authoring platform for creating LaTeX files for submission to publisher submission systems. The Getting Started guide provides helpful information as well as the video tutorials. NOTE: There is an ASCE LaTeX template available in Overleaf.
Beginner's Guide to TeX — This introduction to TeX contains links to a basic explanation of TeX, a more-thorough overview, and FAQs, as well as user help, documentation, sample documents, and a list of recommended reference books.
The Comprehensive TeX Archive Network (CTAN) — To learn about what TeX is and where it came from, visit the CTAN article titled “What is CTAN?” There is a search function for files and documentation on the site, as well as links to sign up for TeX user groups and announcements lists.
LaTeX Encyclopedia — The online LaTeX “encyclopedia” site contains a Table of Contents, with links to information on documentation, installation, typography, and a Navigator for the site.
LaTeX Math Guide — The American Mathematical Society's Short Math Guide for LaTeX.
Submitting the Final Version of the Manuscript
Microsoft Word is ASCE's preferred file format for manuscript text and tables. LaTeX is also acceptable; however, the corresponding author must review page proofs very carefully to ensure that special characters, equations, and other technical material appear correctly. Authors using LaTeX may want to use the ASCE Overleaf template.

All text, including the Abstract and References list, should be prepared in single-column and double-spaced format. Indent or add extra space between all paragraphs. Use a clear, readable font, such as Times New Roman, in 10, 11, or 12-point type. Do not submit any manuscript text smaller than 10 points.

Place tables and double-spaced figure captions on separate pages at the end of the manuscript. Verify that the final version is complete and that all pages are numbered correctly, including figures and tables. Do not include blank pages to separate sections.

Peer Review Process
Once an article is submitted for review, it will be evaluated by ASCE journal staff to ensure it meets our technical requirements for submission. Once the manuscript passes our technical check, the manuscript will be sent to the chief editor of the journal to begin the review process.

ASCE employs a single anonymous peer review process for review. When the manuscript is sent to an editor, the chief editor performs an initial review of the article to ensure it fits the aims and scope of the journal. Authors can review each journal's aims and scope on the journal home page at ASCE Library.

If a manuscript fits within the journal's scope, the chief editor may send the article to an associate editor who will invite reviewers and make a decision on the manuscript. Once the associate editor submits their recommendation and the reviews, the chief editor will review the recommendation and make a final decision.

Guidelines for Publication
To be acceptable for publication, a manuscript must:

Be of value and interest to civil engineers.
Be an original review of past practice, present information, or probe new fields of civil engineering activity.
Contribute to the planning, analysis, design, construction, management, or maintenance of civil engineering works.
Contribute to the advancement of the profession by using the journals as a forum for the exchange of experiences by engineers.
Include a Practical Applications section whenever possible; theoretical manuscripts should indicate areas of additional research to implement technology transfer.
Be free of evident commercialism or private interest but must not obscure proper names when they are required for an understanding of the subject matter.
Be free of personalities, either complimentary or derogatory.
Not be readily available elsewhere—it should not have been published previously by ASCE (including a proceeding) or other professional or technical societies, federal agencies, or commercial publishers.
Be clear and transparent on authorship; ASCE will not review or publish any manuscripts whose authorship is in dispute.
Be consistent with the purpose of the Society and not contain purely speculative matter, although it can use scientific evidence to challenge current concepts or propose new ideas that will encourage progress and discussion.
ASCE Review Decisions
Upon initial review of a submitted manuscript, the editor is permitted to take the following actions:

Send the paper out for review.
Return the paper without review and suggest a transfer of the paper to another ASCE journal.
Return the paper without review because the paper is outside the scope of the journal.
Return the paper without review because the grammar is substandard.
Return the paper without review because the technical content is insufficient.
Return the paper without review because the paper grossly exceeds the length limitations.
Reviewers are experts who critically read and provide detailed reviews to improve the paper. Editors review the comments and will often provide a summary for the authors. The decisions available after review are:

Accept.
Revise.
Decline.
Upon submitting revisions to the journal, authors are required to submit a rebuttal to the reviewer comments. Authors should note the page and line number and fully address all reviewer comments. Even if an author does not agree with the change requested, the author should explain the rationale in the rebuttal. If an editor feels that an author has ignored reviewer comments, the editor may reject the revised manuscript.

Appeal of Review Decisions
An author who disagrees with a review decision may appeal it by contacting the Journal's Editorial Coordinator within 12 months from the decision date. The Coordinator will forward the appeal to the Managing Editor of the journal who will consult with the Chief Editor of the journal to determine if the appeal is valid. If the appeal is deemed valid, the Managing Editor will send the submission back to the authors through the Editorial Manager system to upload their appeal letter with their original submission to be rereviewed. If it is again declined, the decision may be appealed to the appropriate division, council, or institute. The division, council, or institute's decision is final.

The Journal of Geotechnical and Geoenvironmental Engineering has its own appeal process. All appeals for this journal should be sent to the Chief Editor with a copy to the ASCE managing editor. The Chief Editor will review the appeal and if they deem it appropriate, the appeal will be sent to the Ombudsman who will review the paper, reviews, and responses. The Ombudsman will make the decision on the appeal after conferring with the Chief Editor.