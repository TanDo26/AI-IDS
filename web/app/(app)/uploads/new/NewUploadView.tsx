"use client";

import { useRouter } from "next/navigation";

import { UploadDropzone } from "@/components/UploadDropzone";
import { Alert } from "@/components/ui";
import { useNoActiveModel } from "@/lib/readiness";
import { useInvalidateUploads } from "@/lib/uploads";

export function NewUploadView() {
  const router = useRouter();
  const invalidate = useInvalidateUploads();
  const noModel = useNoActiveModel();

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">New upload</h1>
        <p className="mt-1 text-sm text-slate-500">
          A CSV of network flows exported by CICFlowMeter, or a packet capture (pcap / pcapng), whose IPv4
          flows are extracted the way CICFlowMeter extracts them. Only the flow features are used: a{" "}
          <code>Label</code> column in the file is ignored. The model classifies each flow as benign, a known
          attack, or unknown.
        </p>
      </div>
      {noModel && <Alert tone="info">No model is active yet, so uploads can&apos;t be analysed. Ask an admin to activate one.</Alert>}
      <UploadDropzone
        disabled={noModel}
        onUploaded={(upload) => {
          invalidate();
          router.push(`/uploads/${upload.id}`);
        }}
      />
    </div>
  );
}
