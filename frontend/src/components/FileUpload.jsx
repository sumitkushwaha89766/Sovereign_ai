// Local document upload. Uploaded file contents are treated strictly as DATA —
// never executed or interpreted (untrusted input). On success the DB-assigned
// document_id is returned to the caller (proves the round-trip in live mode).
import { useRef, useState } from 'react'
import { uploadDocument } from '../api/documents'

export default function FileUpload({ onUploaded, disabled = false }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function handleUpload() {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const doc = await uploadDocument(file)
      onUploaded?.(doc)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
    } catch {
      setError('Upload failed. Check that the backend is running.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept=".txt,.pdf,.png,.jpg,.jpeg,.tif,.tiff"
          disabled={disabled || busy}
          onChange={(e) => {
            setFile(e.target.files?.[0] || null)
            setError(null)
          }}
          className="input text-sm file:mr-3 file:rounded file:border-0 file:bg-panel2 file:px-3 file:py-1 file:text-text file:font-mono"
        />
        <button className="btn btn-primary shrink-0" onClick={handleUpload} disabled={!file || busy || disabled}>
          {busy ? 'Uploading…' : 'Upload'}
        </button>
      </div>
      <p className="text-xs text-muted">
        Text, scanned PDF, or image. Contents are processed locally as data — never executed.
      </p>
      {error && <p className="text-xs text-trip">{error}</p>}
    </div>
  )
}
