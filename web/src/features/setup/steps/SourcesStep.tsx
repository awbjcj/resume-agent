import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { SourcesManager } from "@/features/sources/SourcesPage";

export function SourcesStep() {
  const navigate = useNavigate();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sources</CardTitle>
        <CardDescription>
          Add at least one board or careers page to pull jobs from.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <SourcesManager />
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/setup/finish")}>Skip for now</Button>
        <Button onClick={() => navigate("/setup/finish")}>Continue</Button>
      </CardFooter>
    </Card>
  );
}
