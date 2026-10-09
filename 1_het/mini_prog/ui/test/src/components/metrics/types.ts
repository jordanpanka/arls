export type ComplexityCategory = "Low" | "Moderate" | "High" | "VeryHigh";

export type ComplexityBand = { category: ComplexityCategory, min: number, max: number | null, label: string };

export type MetricsThresholds = {
    complexityBands: ComplexityBand[],
    highComplexityAbove: number,
    longFunctionNloc: number,
    manyParameters: number
};

export type AnalysisStatus = "Queued" | "Running" | "Completed" | "Partial" | "Failed";

export type MetricsAnalysis = {
    analysisId: number,
    projectId: number,
    repositoryId: number | null,
    status: AnalysisStatus,
    staticStatus: string,
    graphStatus: string,
    errorMessage: string | null,
    trigger: string,
    branch: string | null,
    commitSha: string | null,
    createdAt: string,
    startedAt: string | null,
    completedAt: string | null,
    totalDurationMs: number | null,
    staticDurationMs: number | null,
    graphDurationMs: number | null,
    filesAnalyzed: number,
    filesSkipped: number,
    staticAnalyzer: string,
    graphAnalyzer: string | null
};

export type RepositorySummary = {
    totalFiles: number,
    totalNloc: number,
    totalFunctions: number,
    totalClasses: number | null,
    averageComplexity: number | null,
    maxComplexity: number | null,
    maxComplexityCategory: ComplexityCategory | null,
    highComplexityFunctionCount: number,
    longFunctionCount: number,
    manyParameterFunctionCount: number,
    dependencyCount: number | null,
    cycleCount: number | null,
    averageFanIn: number | null,
    averageFanOut: number | null,
    maxFanIn: number | null,
    maxFanOut: number | null,
    maxDependencyDepth: number | null,
    cycles: string[][]
};

export type DistributionBucket = { category: ComplexityCategory, label: string, count: number };

export type RepositoryMetrics = {
    analysis: MetricsAnalysis,
    summary: RepositorySummary,
    complexityDistribution: DistributionBucket[],
    thresholds: MetricsThresholds,
    skippedFiles: { path: string, reason: string }[]
};

export type FileMetric = {
    id: number,
    fileId: number | null,
    path: string,
    language: string,
    nloc: number,
    tokenCount: number,
    functionCount: number,
    classCount: number | null,
    averageComplexity: number | null,
    maxComplexity: number | null,
    complexityCategory: ComplexityCategory | null,
    highComplexityFunctionCount: number,
    averageFunctionNloc: number | null,
    maxFunctionNloc: number | null,
    longFunctionCount: number,
    manyParameterFunctionCount: number,
    fanIn: number | null,
    fanOut: number | null,
    importCount: number | null
};

export type FunctionMetric = {
    id: number,
    fileId: number | null,
    filePath: string,
    name: string,
    longName: string,
    className: string | null,
    startLine: number,
    endLine: number,
    nloc: number,
    cyclomaticComplexity: number,
    complexityCategory: ComplexityCategory,
    tokenCount: number,
    parameterCount: number,
    length: number,
    fanIn: number | null,
    fanOut: number | null,
    isLong: boolean,
    hasManyParameters: boolean
};

export type FileMetricsDetail = { analysis: MetricsAnalysis, file: FileMetric, functions: FunctionMetric[] };

export type Hotspots = { kind: string, files: FileMetric[], functions: FunctionMetric[] };

export type MetricsStatus = { latest: MetricsAnalysis | null, latestUsable: MetricsAnalysis | null };

export type AnalyzeResponse = { analysisId: number, status: AnalysisStatus, reused: boolean };
