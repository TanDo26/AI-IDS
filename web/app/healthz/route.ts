// Liveness for the container healthcheck (docker-compose.yml); the API has its own /api/v1/healthz
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
