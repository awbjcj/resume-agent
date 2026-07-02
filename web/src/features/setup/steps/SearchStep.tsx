import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchConfigForm } from "@/features/settings/forms/SearchConfigForm";
import { useConfig, useSaveConfig } from "@/features/settings/use-config";
import { useDraft } from "@/features/settings/use-draft";
import type { paths } from "@/lib/api/schema";

type SearchDoc = paths["/api/config/search"]["get"]["responses"][200]["content"]["application/json"];

export function SearchStep() {
  const { data } = useConfig("/api/config/search");
  const save = useSaveConfig("/api/config/search");
  const { draft, setDraft } = useDraft(data as SearchDoc | undefined);
  const navigate = useNavigate();

  const continueToNext = () => {
    if (draft) save.mutate(draft);
    navigate("/setup/sources");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search</CardTitle>
        <CardDescription>What discovery looks for.</CardDescription>
      </CardHeader>
      <CardContent>
        {draft && <SearchConfigForm value={draft} onChange={setDraft} />}
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/setup/sources")}>Skip for now</Button>
        <Button onClick={continueToNext}>Save & continue</Button>
      </CardFooter>
    </Card>
  );
}
