import type { ProjectFile } from "./types";

export type FileErrorKind = "not-found" | "forbidden" | "unauthorized" | "unsupported" | "failed";

export class FileLoadError extends Error {
    kind: FileErrorKind;

    constructor(kind: FileErrorKind, message: string) {
        super(message);
        this.kind = kind;
    }
}

const MESSAGES: Record<FileErrorKind, string> = {
    "not-found": "This file could not be found. It may have been removed or re-uploaded.",
    "forbidden": "You don't have access to this file.",
    "unauthorized": "Your session has expired, please sign in again.",
    "unsupported": "This file type can't be previewed.",
    "failed": "The file could not be loaded."
};

function kindFromStatus(status: number): FileErrorKind {
    if (status === 404) return "not-found";
    if (status === 403) return "forbidden";
    if (status === 401) return "unauthorized";
    if (status === 415) return "unsupported";
    return "failed";
}

const cache = new Map<string, Promise<ProjectFile>>();

async function fetchProjectFile(projectId: number, fileId: string): Promise<ProjectFile> {
    const token = localStorage.getItem("token");
    let response: Response;
    try {
        response = await fetch(`/api/projects/${projectId}/files/${encodeURIComponent(fileId)}`, {
            headers: { "Authorization": "Bearer " + token }
        });
    } catch {
        throw new FileLoadError("failed", MESSAGES.failed);
    }

    if (!response.ok) {
        const kind = kindFromStatus(response.status);
        throw new FileLoadError(kind, MESSAGES[kind]);
    }
    return await response.json();
}

/** Loaded files stay cached for the session; failed requests are not cached so they can be retried. */
export function loadProjectFile(projectId: number, fileId: string): Promise<ProjectFile> {
    const key = `${projectId}:${fileId}`;
    const cached = cache.get(key);
    if (cached) return cached;

    const request = fetchProjectFile(projectId, fileId).catch(error => {
        cache.delete(key);
        throw error;
    });
    cache.set(key, request);
    return request;
}

export function clearFileCache() {
    cache.clear();
}
