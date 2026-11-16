import { RouteLoading } from "@/components/console/routeLoading";

/** Every operator screen without its own, while it opens. The shell stays around it. */
export default function AdminScreenLoading() {
  return <RouteLoading label="Opening this screen" />;
}
