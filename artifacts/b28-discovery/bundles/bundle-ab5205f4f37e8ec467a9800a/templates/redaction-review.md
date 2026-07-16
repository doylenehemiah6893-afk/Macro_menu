# Image redaction review

Images are private raw evidence and must never be committed to the public repository.

Before `add-operator-record`, create a canonical ASCII JSON file beside the image. For
`screen.png`, name it `screen.redaction-review.json`:

```json
{"decision":"approved-redacted","image_sha256":"REPLACE_WITH_LOWERCASE_SHA256","review_record_ids":["record-review-first","record-review-second"],"schema_version":1}
```

The two review record IDs must identify different reviewers. Confirm that all
environment-specific details have been removed from the image.
