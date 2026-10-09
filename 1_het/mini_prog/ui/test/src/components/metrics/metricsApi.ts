import type { AnalyzeResponse, FileMetric, FileMetricsDetail, Hotspots, MetricsStatus, RepositoryMetrics } from "./types";

export class MetricsApiError extends Error {
    status: number;
    code: string;

    constructor(status: number, code: string, message: string) {
        super(message);
        this.status = status;
        this.code = code;
    }
}

function describe(status: number, fallback: string): string {
    if (status === 401) return "Your session has expired. Please log in again.";
    if (status === 403) return "You don't have access to this project.";
    if (status === 0) return "The server could not be reached.";
    return fallback;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
    const token = localStorage.getItem("token");
    let response: Response;
    try {
        response = await fetch(url, {
            ...init,
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token, ...(init?.headers ?? {}) }
        });
    } catch {
        throw new MetricsApiError(0, "network", describe(0, ""));
    }

    if (!response.ok) {
        let code = "error";
        let message = "Loading code metrics failed.";
        try {
            const body = await response.json();
            code = body?.error ?? code;
            message = body?.message ?? message;
        } catch {
        }
        throw new MetricsApiError(response.status, code, describe(response.status, message));
    }

    return await response.json() as T;
}

const base = (projectId: number) => `/api/projects/${projectId}/metrics`;

export const metricsApi = {
    status: (projectId: number) => request<MetricsStatus>(`${base(projectId)}/status`),
    repository: (projectId: number) => request<RepositoryMetrics>(base(projectId)),
    files: (projectId: number, sort = "maxComplexity", limit = 200) =>
        request<FileMetric[]>(`${base(projectId)}/files?sort=${encodeURIComponent(sort)}&desc=true&limit=${limit}`),
    fileDetail: (projectId: number, path: string) =>
        request<FileMetricsDetail>(`${base(projectId)}/files/detail?path=${encodeURIComponent(path)}`),
    hotspots: (projectId: number, kind: "complexity" | "dependencies" | "maintainability", limit = 10) =>
        request<Hotspots>(`${base(projectId)}/hotspots/${kind}?limit=${limit}`),
    analyze: (projectId: number, force: boolean) =>
        request<AnalyzeResponse>(`${base(projectId)}/analyze`, { method: "POST", body: JSON.stringify({ force }) })
};

export function isNoAnalysis(error: unknown): boolean {
    return error instanceof MetricsApiError && error.code === "no_analysis";
}
