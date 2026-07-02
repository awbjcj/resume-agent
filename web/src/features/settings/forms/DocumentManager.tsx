import { useRef, useState } from "react";
import { FileUp, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useDeleteDocument, useDocuments, useUploadDocument } from "../use-documents";

const DOC_TYPES = ["resume", "transcript", "portfolio", "other"] as const;

export function DocumentManager() {
  const docs = useDocuments();
  const upload = useUploadDocument();
  const del = useDeleteDocument();
  const [docType, setDocType] = useState<string>("resume");
  const fileInput = useRef<HTMLInputElement>(null);

  const handleFiles = (files: FileList | null) => {
    if (files?.[0]) upload.mutate({ file: files[0], docType });
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
      >
        <FileUp className="size-6 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Drop a document here — PDF, DOCX, TXT, or Markdown, up to 15 MB
        </p>
        <div className="flex items-center gap-2">
          <Select value={docType} onValueChange={(v) => v && setDocType(v)}>
            <SelectTrigger className="w-36" aria-label="Document type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {DOC_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => fileInput.current?.click()}>
            Choose file
          </Button>
          <input ref={fileInput} data-testid="file-input" type="file" className="hidden"
            accept=".pdf,.docx,.txt,.md" onChange={(e) => handleFiles(e.target.files)} />
        </div>
      </div>

      {docs.data && docs.data.length === 0 && (
        <Empty>No documents yet — your resume is the one that matters most.</Empty>
      )}
      {docs.data && docs.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Uploaded</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {docs.data.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">{doc.filename}</TableCell>
                <TableCell><Badge variant="secondary">{doc.docType}</Badge></TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(doc.uploadedAt).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <ConfirmDialog
                    trigger={
                      <Button variant="ghost" size="sm" aria-label={`Delete ${doc.filename}`}>
                        <Trash2 aria-hidden="true" />
                      </Button>
                    }
                    title={`Delete ${doc.filename}?`}
                    description="The file is removed permanently. Facts already extracted stay until the next profile build."
                    confirmLabel="Delete document"
                    onConfirm={() => del.mutate(doc.id)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
