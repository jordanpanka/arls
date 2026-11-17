import { Box, CircularProgress, Paper, Typography } from "@mui/material";
import { useEffect, useState } from "preact/hooks";

export function ThinkingIndicator() {
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        const started = Date.now();
        const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
        return () => clearInterval(timer);
    }, []);

    return (
        <Box sx={{ display: "flex", justifyContent: "flex-start", mr: "50px", ml: "50px" }}>
            <Paper sx={{ margin: "1px", mt: "5px", mb: "5px", px: "12px", py: "10px", display: "flex", alignItems: "center", gap: 1.5 }} role="status" aria-live="polite">
                <CircularProgress size={18} thickness={5} sx={{ color: "#0077B6" }} />
                <Typography sx={{ color: "text.secondary" }}>Thinking…</Typography>
                {elapsed > 0 && <Typography sx={{ fontSize: 12, color: "text.disabled" }}>{`${elapsed} s`}</Typography>}
            </Paper>
        </Box>
    );
}
