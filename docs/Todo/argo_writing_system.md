# ARGO Writing & Document Handling Guide

This guide explains how to use ARGO to manage writing, documents,
emails, notes, and blog posts through voice commands.

------------------------------------------------------------------------

# 1. Create a Writing Workspace

    /argo_data
       /incoming_docs
       /processed_docs
       /drafts
          /emails
          /blogs
          /notes
       /published

Purpose:

-   **incoming_docs** -- drop PDFs, DOCX, scans
-   **processed_docs** -- documents after indexing
-   **drafts** -- anything ARGO writes
-   **published** -- final blog posts or articles

------------------------------------------------------------------------

# 2. Ingest Documents

Whenever a file is placed in `incoming_docs`, ARGO processes it.

## Extract Text

Recommended libraries:

-   PDF → pymupdf
-   DOCX → python-docx
-   TXT / MD → direct read
-   Images → tesseract OCR

Example:

    text = extract_text(file)

------------------------------------------------------------------------

## Split Into Chunks

Large documents must be split.

Recommended size:

    500–800 words per chunk

Metadata example:

    source_file
    title
    date
    topic
    chunk_text

------------------------------------------------------------------------

## Create Embeddings

Use an embedding model so ARGO can search your documents.

    text-embedding-3-small

Example:

    vector = embedding(chunk_text)

------------------------------------------------------------------------

## Store In Database

Example SQLite schema:

    documents
    ---------
    id
    source
    chunk_text
    embedding
    created_at
    tags

------------------------------------------------------------------------

# 3. Retrieval

Example question:

> ARGO what did I write about running the Cat Club?

System process:

1.  Convert question to embedding
2.  Search vector database
3.  Retrieve top matches
4.  Send those chunks to GPT

Prompt example:

    Relevant text from Tommy's documents:

    [chunk 1]
    [chunk 2]
    [chunk 3]

    Question:
    What did Tommy write about running the Cat Club?

------------------------------------------------------------------------

# 4. Email Writing Workflow

Voice command:

> ARGO write an email to Paul about organizing the photo drives.

Pipeline:

    speech
    ↓
    STT
    ↓
    intent = WRITE_EMAIL
    ↓
    GPT generates draft
    ↓
    draft saved
    ↓
    ARGO reads draft
    ↓
    user confirms
    ↓
    send email

Saved here:

    /drafts/emails/email_YYYY_MM_DD.txt

------------------------------------------------------------------------

# 5. Blog Writing

Example command:

> ARGO write a blog post about the night the fire marshal shut down the
> Cat Club.

Prompt example:

    Write a blog post in Tommy's storytelling style.

    Topic:
    Cat Club shutdown by fire marshal

    Tone:
    Humorous and reflective

Saved to:

    /drafts/blogs/cat_club_shutdown.md

------------------------------------------------------------------------

# 6. Quick Voice Notes

Command:

> ARGO take a note

Saved automatically:

    /drafts/notes/note_YYYY_MM_DD.txt

Example:

    Idea: Blog about tuna boat storm
    Mention radar failure
    Mention deckhand slipping

------------------------------------------------------------------------

# 7. Sending Email

Always require confirmation.

Example:

User: Send it.

Then ARGO calls:

    send_email(
      to="example@email.com",
      subject="Photo archive project",
      body=email_text
    )

Common email APIs:

-   Gmail API
-   SMTP
-   Microsoft Graph

------------------------------------------------------------------------

# 8. Editing Drafts By Voice

Commands:

    make it shorter
    make it funnier
    add a paragraph about Jesse
    change tone to serious

ARGO edits the stored draft.

------------------------------------------------------------------------

# 9. Use Your Past Writing

Because your documents are indexed, prompts can include:

    Use Tommy's previous writing style from autobiography drafts.

This keeps output consistent with your voice.

------------------------------------------------------------------------

# 10. Search Your Writing

Voice examples:

    ARGO find the story about the tuna boat storm
    ARGO pull the Cat Club chapter
    ARGO summarize my last blog draft
    ARGO what did I write about Jesse cooking

------------------------------------------------------------------------

# 11. Add Tags During Ingestion

Example tags:

    topic: nightlife
    topic: fishing
    topic: Jesse
    topic: cooking
    topic: autobiography

Tags make retrieval faster.

------------------------------------------------------------------------

# 12. Full System Flow

    Mic
    ↓
    OpenAI realtime speech
    ↓
    Intent detection
    ↓
    Memory system
    ↓
    Document retrieval
    ↓
    GPT-4o-mini
    ↓
    TTS response

ARGO can now:

-   write emails
-   draft blog posts
-   store voice notes
-   search your documents
-   quote your past writing
-   edit drafts by voice
