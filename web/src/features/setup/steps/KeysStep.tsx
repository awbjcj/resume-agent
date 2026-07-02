import { useNavigate } from "react-router-dom";

import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { SecretsForm } from "@/features/settings/forms/SecretsForm";
import { useSaveSecrets, useSecrets } from "@/features/settings/use-secrets";

export function KeysStep() {
  const secrets = useSecrets();
  const saveSecrets = useSaveSecrets();
  const navigate = useNavigate();

  const primary = (secrets.data ?? []).filter((s) => s.key === "anthropicApiKey");
  const rest = (secrets.data ?? []).filter((s) => s.key !== "anthropicApiKey");

  return (
    <Card>
      <CardHeader>
        <CardTitle>API keys</CardTitle>
        <CardDescription>
          Needed for tailoring — everything else works without it.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {secrets.data && (
          <>
            <SecretsForm statuses={primary} saving={saveSecrets.isPending}
              onSave={(patch) => saveSecrets.mutate(patch)} />
            <Accordion>
              <AccordionItem value="more">
                <AccordionTrigger>More providers & sources</AccordionTrigger>
                <AccordionContent>
                  <SecretsForm statuses={rest} saving={saveSecrets.isPending}
                    onSave={(patch) => saveSecrets.mutate(patch)} />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </>
        )}
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/setup/documents")}>
          Skip for now
        </Button>
        <Button onClick={() => navigate("/setup/documents")}>Save & continue</Button>
      </CardFooter>
    </Card>
  );
}
