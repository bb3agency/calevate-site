import { RouteLoading } from "@/components/console/routeLoading";

/** Every client screen without its own, while its code arrives. The shell stays around it. */
export default function Loading() {
  return <RouteLoading label="Opening…" />;
}
