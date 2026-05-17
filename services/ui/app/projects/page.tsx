import { getProjects } from "@/lib/api";
import ProjectsClient from "./projects-client";

export default async function ProjectsPage() {
  let projects;
  let error: string | null = null;

  try {
    projects = await getProjects();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load projects";
    projects = [];
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <ProjectsClient initialProjects={projects} />
    </div>
  );
}
