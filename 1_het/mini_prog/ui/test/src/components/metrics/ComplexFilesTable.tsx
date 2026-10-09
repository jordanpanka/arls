import { Box, Table, TableBody, TableCell, TableHead, TableRow, TableSortLabel, Typography } from "@mui/material";
import { useMemo, useState } from "preact/hooks";
import { CATEGORY_COLORS, CATEGORY_LABELS, MUTED, fileName, formatDecimal, formatNumber } from "./format";
import type { FileMetric } from "./types";

type SortKey = "path" | "nloc" | "functionCount" | "averageComplexity" | "maxComplexity" | "fanIn" | "fanOut";

const COLUMNS: { key: SortKey, label: string, numeric: boolean }[] = [
    { key: "path", label: "File", numeric: false },
    { key: "nloc", label: "LOC", numeric: true },
    { key: "functionCount", label: "Functions", numeric: true },
    { key: "averageComplexity", label: "Avg CC", numeric: true },
    { key: "maxComplexity", label: "Max CC", numeric: true },
    { key: "fanIn", label: "Fan-in", numeric: true },
    { key: "fanOut", label: "Fan-out", numeric: true }
];

const cellSx = { fontSize: 13, py: 1, borderColor: "#eef2f7", fontVariantNumeric: "tabular-nums" };

type Props = { files: FileMetric[], onOpenFile: (path: string) => void, limit?: number };

export function ComplexFilesTable({ files, onOpenFile, limit = 15 }: Props) {
    const [sort, setSort] = useState<SortKey>("maxComplexity");
    const [desc, setDesc] = useState(true);

    const rows = useMemo(() => {
        const sorted = [...files].sort((a, b) => {
            const av = a[sort];
            const bv = b[sort];
            if (av === bv) return 0;
            if (av === null) return 1;
            if (bv === null) return -1;
            const order = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
            return desc ? -order : order;
        });
        return sorted.slice(0, limit);
    }, [files, sort, desc, limit]);

    function toggle(key: SortKey) {
        if (key === sort) setDesc(d => !d);
        else {
            setSort(key);
            setDesc(key !== "path");
        }
    }

    if (files.length === 0) {
        return <Typography sx={{ fontSize: 13, color: MUTED }}>No files were analyzed.</Typography>;
    }

    return (
        <Box sx={{ overflowX: "auto" }}>
            <Table size="small" aria-label="Most complex files">
                <TableHead>
                    <TableRow>
                        {COLUMNS.map(column => (
                            <TableCell key={column.key} align={column.numeric ? "right" : "left"} sx={{ ...cellSx, fontWeight: 600, color: "#475569" }} sortDirection={sort === column.key ? (desc ? "desc" : "asc") : false}>
                                <TableSortLabel active={sort === column.key} direction={sort === column.key && !desc ? "asc" : "desc"} onClick={() => toggle(column.key)} sx={{ height: "auto" }}>
                                    {column.label}
                                </TableSortLabel>
                            </TableCell>
                        ))}
                    </TableRow>
                </TableHead>
                <TableBody>
                    {rows.map(file => (
                        <TableRow key={file.id} hover onClick={() => onOpenFile(file.path)} sx={{ cursor: "pointer" }} data-testid={`file-row-${file.path}`}>
                            <TableCell sx={{ ...cellSx, maxWidth: 360 }} title={file.path}>
                                <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}>
                                    {file.complexityCategory && (
                                        <Box aria-hidden sx={{ width: 10, height: 10, borderRadius: "3px", flexShrink: 0, bgcolor: CATEGORY_COLORS[file.complexityCategory] }} />
                                    )}
                                    <Box sx={{ minWidth: 0 }}>
                                        <Typography sx={{ fontSize: 13, fontWeight: 500, color: "#334155", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fileName(file.path)}</Typography>
                                        <Typography sx={{ fontSize: 11, color: MUTED, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                            {file.path}{file.complexityCategory ? ` · ${CATEGORY_LABELS[file.complexityCategory]}` : ""}
                                        </Typography>
                                    </Box>
                                </Box>
                            </TableCell>
                            <TableCell align="right" sx={cellSx}>{formatNumber(file.nloc)}</TableCell>
                            <TableCell align="right" sx={cellSx}>{formatNumber(file.functionCount)}</TableCell>
                            <TableCell align="right" sx={cellSx}>{formatDecimal(file.averageComplexity)}</TableCell>
                            <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }}>{formatNumber(file.maxComplexity)}</TableCell>
                            <TableCell align="right" sx={cellSx}>{formatNumber(file.fanIn)}</TableCell>
                            <TableCell align="right" sx={cellSx}>{formatNumber(file.fanOut)}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Box>
    );
}
