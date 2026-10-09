import { Box, Typography } from "@mui/material";
import type { ComponentChildren } from "preact";
import { BORDER, MUTED, NAVY } from "./format";

type SectionProps = {
    title: string,
    subtitle?: string,
    action?: ComponentChildren,
    children: ComponentChildren
};

export function Section({ title, subtitle, action, children }: SectionProps) {
    return (
        <Box component="section" aria-label={title} sx={{ bgcolor: "white", border: `1px solid ${BORDER}`, borderRadius: "14px", p: 2.5, minWidth: 0 }}>
            <Box sx={{ display: "flex", alignItems: "flex-start", gap: 2, mb: 2 }}>
                <Box sx={{ minWidth: 0 }}>
                    <Typography component="h2" sx={{ fontFamily: "'Inter', sans-serif", fontWeight: 600, fontSize: 16, color: NAVY }}>{title}</Typography>
                    {subtitle && <Typography sx={{ fontSize: 13, color: MUTED, mt: 0.25 }}>{subtitle}</Typography>}
                </Box>
                {action && <Box sx={{ ml: "auto", flexShrink: 0 }}>{action}</Box>}
            </Box>
            {children}
        </Box>
    );
}
