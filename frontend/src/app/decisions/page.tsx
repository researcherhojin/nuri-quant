export const dynamic = "force-dynamic";

import DecisionsView from "./page-view";

export default function DecisionsPage(props: {
  searchParams?: Promise<{ outcome?: string; action?: string }>;
}) {
  return <DecisionsView {...props} />;
}
