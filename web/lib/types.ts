/**
 * API types, generated from the backend's OpenAPI schema (never edit api-schema.d.ts by hand):
 *   python scripts/export_openapi.py && cd web && npm run gen:api
 */
import type { components } from "@/lib/api-schema";

type Schemas = components["schemas"];

// auth
export type User = Schemas["UserOut"];
export type TokenResponse = Schemas["TokenResponse"];
export type LoginRequest = Schemas["LoginRequest"];
export type SignupRequest = Schemas["SignupRequest"];
export type PasswordChangeRequest = Schemas["PasswordChangeRequest"];

// uploads and results
export type Upload = Schemas["UploadOut"];
export type UploadPage = Schemas["UploadPage"];
export type UploadStatus = Upload["status"];
export type UploadTotals = Schemas["UploadTotals"];
export type Summary = Schemas["SummaryOut"];
export type Flow = Schemas["FlowOut"];
export type FlowPage = Schemas["FlowPage"];
export type Decision = Flow["decision"];
export type Explanation = Schemas["ExplanationOut"];
export type Attribution = Schemas["Explanation"];      // one target's SHAP contributions
export type Contribution = Schemas["Contribution"];

// admin
export type ModelsOverview = Schemas["ModelsOverview"];
export type ModelVersion = Schemas["ModelVersionOut"];
export type ModelMetrics = Schemas["ModelMetrics"];
export type ProcessModel = Schemas["ProcessModel"];
export type RescanResult = Schemas["RescanOut"];
export type Activation = Schemas["ActivationOut"];
export type ServerStatus = Schemas["ServerStatus"];
export type AdminUser = Schemas["UserAdminOut"];
export type UserPage = Schemas["UserPage"];
export type UserUpdate = Schemas["UserUpdate"];
export type Usage = Schemas["UsageOut"];
export type UsageRow = Schemas["UsageRow"];
export type DailyUsage = Schemas["DailyUsageOut"];
export type UsageDay = Schemas["DailyUsage"];         // one UTC day of DailyUsage
export type AdminUploadPage = Schemas["AdminUploadPage"];
export type AuditPage = Schemas["AuditPage"];
export type AuditEntry = Schemas["AuditOut"];

// /readyz (not a declared response model)
export interface Readiness {
  ready: boolean;
  checks: Record<string, { ok: boolean; error?: string } & Record<string, unknown>>;
}
