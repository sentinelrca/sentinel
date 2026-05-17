"use client";

import { useState } from "react";
import ProjectCard from "@/components/project-card";
import CreateProjectDialog from "@/components/create-project-dialog";
import type { Project } from "@/lib/types";

interface Props {
  initialProjects: Project[];
}

export default function ProjectsClient({ initialProjects }: Props) {
  const [projects, setProjects] = useState<Project[]>(initialProjects);

  function handleCreated(project: Project) {
    setProjects((prev) => [project, ...prev]);
  }

  return (
    <>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
          <p className="mt-1 text-sm text-slate-500">
            {projects.length === 0
              ? "Group traces and analyze them together"
              : `${projects.length} project${projects.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <CreateProjectDialog onCreated={handleCreated} />
      </div>

      {projects.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          No projects yet. Create a project to group traces and run batch analysis.
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </>
  );
}
