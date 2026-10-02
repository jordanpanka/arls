import { Box } from "@mui/material";
import { useEffect, useRef, useState } from "preact/hooks";
import { EvidencePanel } from "../evidence/EvidencePanel";
import { openPanel, type PanelState } from "../evidence/panelState";
import { ChatWindow } from "./Chat";

type ChatAreaProps = {
    newChat: boolean,
    setNewChat: (b: boolean) => void,
    selectedInvId: number,
    sellectedProjId: number,
    selectedCOnversationId: number,
    setSelectedConversationId: (id: number) => void,
    onPanelOpenChange?: (open: boolean) => void
}

const MIN_WIDTH = 25;
const MAX_WIDTH = 70;

export function ChatArea(props: ChatAreaProps) {
    const [panel, setPanel] = useState<PanelState | null>(null);
    const [width, setWidth] = useState(42);
    const [fullscreen, setFullscreen] = useState(false);
    const container = useRef<HTMLDivElement>(null);

    useEffect(() => {
        setPanel(null);
        setFullscreen(false);
    }, [props.sellectedProjId, props.selectedCOnversationId]);

    const panelOpen = panel !== null;
    useEffect(() => { props.onPanelOpenChange?.(panelOpen); }, [panelOpen]);

    function startResize(event: PointerEvent) {
        event.preventDefault();
        const rect = container.current?.getBoundingClientRect();
        if (!rect) return;

        const move = (e: PointerEvent) => {
            const percent = ((rect.right - e.clientX) / rect.width) * 100;
            setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, percent)));
        };
        const stop = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", stop);
            document.body.style.userSelect = "";
        };
        document.body.style.userSelect = "none";
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
    }

    function close() {
        setPanel(null);
        setFullscreen(false);
    }

    return (
        <Box ref={container} data-testid="chat-area" sx={{ display: "flex", flex: 1, minWidth: 0, minHeight: 0, height: "100%", width: "100%" }}>
            <Box sx={{ display: panel && fullscreen ? "none" : "flex", flex: 1, minWidth: 0, minHeight: 0, justifyContent: "center" }}>
                <ChatWindow
                    newChat={props.newChat}
                    setNewChat={props.setNewChat}
                    selectedInvId={props.selectedInvId}
                    sellectedProjId={props.sellectedProjId}
                    selectedCOnversationId={props.selectedCOnversationId}
                    setSelectedConversationId={props.setSelectedConversationId}
                    onOpenEvidence={(evidence, id) => setPanel(openPanel(evidence, id))} />
            </Box>
            {panel && (
                <>
                    {!fullscreen && (
                        <Box
                            role="separator"
                            aria-orientation="vertical"
                            aria-label="Resize evidence panel"
                            onPointerDown={startResize}
                            sx={{
                                // A 1px-es vonal mellett egy szélesebb, láthatatlan sáv adja a fogófelületet.
                                width: "1px", flexShrink: 0, position: "relative", zIndex: 1, cursor: "col-resize", bgcolor: "#e5e7eb",
                                "&::before": { content: '""', position: "absolute", top: 0, bottom: 0, left: -3, right: -3 },
                                "&:hover": { bgcolor: "#88B8F9" }
                            }}
                        />
                    )}
                    <Box sx={{ width: fullscreen ? "100%" : `${width}%`, flexShrink: 0, minWidth: 0, minHeight: 0 }}>
                        <EvidencePanel
                            projectId={props.sellectedProjId}
                            state={panel}
                            fullscreen={fullscreen}
                            onChange={setPanel}
                            onToggleFullscreen={() => setFullscreen(f => !f)}
                            onClose={close}
                        />
                    </Box>
                </>
            )}
        </Box>
    );
}
