import type { ComplexityCategory } from "./types";

export const CATEGORY_COLORS: Record<ComplexityCategory, string> = {
    Low: "#9cc5ee",
    Moderate: "#5b9bd5",
    High: "#0077b6",
    VeryHigh: "#03045e"
};

export const CATEGORY_TEXT: Record<ComplexityCategory, string> = {
    Low: "#03045e",
    Moderate: "#03045e",
    High: "#ffffff",
    VeryHigh: "#ffffff"
};

export const CATEGORY_LABELS: Record<ComplexityCategory, string> = {
    Low: "Low",
    Moderate: "Moderate",
    High: "High",
    VeryHigh: "Very high"
};

export const NAVY = "#03045e";
export const MUTED = "#5b6b7f";
export const BORDER = "#e5e7eb";

export function formatNumber(value: number | null | undefined, digits = 0): string {
    if (value === null || value === undefined) return "—";
    return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatDecimal(value: number | null | undefined): string {
    return formatNumber(value, 1);
}

export function formatDate(value: string | null | undefined): string {
    if (!value) return "—";
    const date = new Date(value.endsWith("Z") || value.includes("+") ? value : value + "Z");
    return date.toLocaleString();
}

export function formatDuration(ms: number | null | undefined): string {
    if (ms === null || ms === undefined) return "—";
    return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function fileName(path: string): string {
    return path.split("/").pop() || path;
}
