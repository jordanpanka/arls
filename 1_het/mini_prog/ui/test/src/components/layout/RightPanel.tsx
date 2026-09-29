import { Box, Collapse, Drawer, IconButton, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "preact/hooks";
import { AttachFile, ExpandLess, ExpandMore } from "@mui/icons-material";
import { UploadFile, type RepoForm } from "../upload/uploadFile";
import type { Project } from "./ProjectBar";
import { buildTree, FolderTree, type FileItem } from "./FolderTree";

const openWidth = 240;
const closedWidth = 60;
const HEADER_H = 64;

/** Ahogy a backend RepositoryIngestService adja vissza. */
export type RepoItem = {
    id: number,
    owner: string,
    name: string,
    status: string,
    error: string | null,
    indexed: number,
    total: number,
    skipped: number,
    commitSha: string
};

const POLL_MS = 3000;
const FINISHED = ["Ready", "Failed"];
const SESSION_EXPIRED = "Your session has expired, please sign in again.";

/** A token egy óráig él, így ez import közben is bármikor előjöhet. */
class SessionExpiredError extends Error { }

/**
 * A backend hibái sima szövegként jönnek, de a 401-nek üres a törzse —
 * enélkül a felhasználó egy üres hibaüzenetet kapna.
 */
async function describeHttpError(response: Response) {
    if (response.status === 401) return SESSION_EXPIRED;
    const body = await response.text();
    return body || `The request failed with status ${response.status}.`;
}

function describeRepo(item: RepoItem) {
    switch (item.status) {
        case "Queued":
            return "Queued…";
        case "Fetching":
            return "Downloading the archive from GitHub…";
        case "Indexing":
            return item.total > 0
                ? `Indexing: ${item.indexed}/${item.total} files`
                : "Preparing files…";
        case "Ready":
            return `Done: ${item.indexed} files indexed, ${item.skipped} skipped (${item.commitSha.slice(0, 7)}).`;
        case "Failed":
            return `Error: ${item.error ?? "unknown error"}`;
        default:
            return item.status;
    }
}
type RightPanelProps = {
    selectedInvId:number,
    projectSelected: Project,
    projOpen: Record<number, boolean>,
    setProjOpen: React.Dispatch<React.SetStateAction<Record<number, boolean>>>
    showWindowAddfile:boolean,
    setShowWindowAddFile:(b:boolean)=>void
}

export function RightPanel(rpProps: RightPanelProps) {
    const [open, setOpen] = useState(true);
    const [filesByProjId, setFilesByProjId] = useState<Record<number, FileItem[]>>([]);
    //const [showWindowAddfile, setShowWindowAddFile] = useState(false);
    const [uploadResult, setUploadResult] = useState("");
    const [file, setFile] = useState<FileList>();
    const [repo, setRepo] = useState<RepoForm>({ owner: "", name: "", reference: "" });
    const [busy, setBusy] = useState(false);
    const [watchedRepoId, setWatchedRepoId] = useState<number | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    async function loadFiles(id: number) {
        const token = localStorage.getItem("token");
        const response = await fetch("api/investigations/projects/files/load", {
            method: "Post",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ id })
        })
        const data = await response.json();
        setFilesByProjId(prev => ({
            ...prev,
            [id]: data
        }));
    }
    async function addFile() {
        rpProps.setShowWindowAddFile(true);
    }
    async function link() {
        if (!file) {
            setUploadResult("Choose a file first.");
            return;
        }

        const data = new FormData();
        data.append("projectId", String(rpProps.projectSelected.id));
        for (const f of Array.from(file ?? [])) {
            data.append("files", f);
            const path = f.webkitRelativePath || f.name;
            data.append("paths", path);
        }
        data.append("invId",String(rpProps.selectedInvId));
        data.append("projectId",String(rpProps.projectSelected.id))
        
        const token = localStorage.getItem("token");
        const response = await fetch("/api/investigations/projects/files/upload", {
            method: "POST",
            headers: { "Authorization": "Bearer " + token },
            body: data
        })
        rpProps.setShowWindowAddFile(false);

    }
    async function loadRepos(projectId: number): Promise<RepoItem[]> {
        const token = localStorage.getItem("token");
        const response = await fetch("/api/investigations/projects/repositories/load", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ id: projectId })
        });
        if (response.status === 401) throw new SessionExpiredError();
        if (!response.ok) return [];
        return await response.json();
    }

    async function importRepo() {
        if (!repo.owner.trim() || !repo.name.trim()) {
            setUploadResult("Enter the repository owner and name.");
            return;
        }

        setBusy(true);
        setUploadResult("");
        try {
            const token = localStorage.getItem("token");
            const response = await fetch("/api/investigations/projects/repositories/add", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token
                },
                body: JSON.stringify({
                    invId: rpProps.selectedInvId,
                    projectId: rpProps.projectSelected.id,
                    owner: repo.owner.trim(),
                    repo: repo.name.trim(),
                    // Üresen hagyva a backend HEAD-et használ.
                    reference: repo.reference.trim()
                })
            });

            if (!response.ok) {
                setUploadResult(await describeHttpError(response));
                setBusy(false);
                return;
            }

            // 202: a backend csak sorba állította. Innentől a pollozás követi,
            // és az állítja vissza a busy flaget, amikor tényleg véget ér.
            const data = await response.json();
            setUploadResult(describeRepo({ status: "Queued", indexed: 0, total: 0 } as RepoItem));
            setWatchedRepoId(data.repositoryId);
        } catch {
            setUploadResult("Could not import the repository.");
            setBusy(false);
        }
    }
    // Az import a backend háttérszálán fut, nem a kérésben, így a státuszát
    // pollozni kell. Ez az egyetlen hely, ami a busy flaget visszaveszi.
    useEffect(() => {
        if (watchedRepoId == null) return;

        const projectId = rpProps.projectSelected.id;

        async function check() {
            try {
                const items = await loadRepos(projectId);
                const item = items.find(r => r.id === watchedRepoId);
                if (!item) return;

                setUploadResult(describeRepo(item));

                if (!FINISHED.includes(item.status)) return;

                setWatchedRepoId(null);
                setBusy(false);

                if (item.status === "Ready") {
                    await loadFiles(projectId);
                    rpProps.setProjOpen(s => ({ ...s, [projectId]: true }));
                }
            } catch (e) {
                // A lejárt tokentől a pollozás sosem jutna eredményre, ezért
                // inkább leállunk és megmondjuk, miért. Minden más hiba lehet
                // átmeneti, azt a következő kör újrapróbálja.
                if (e instanceof SessionExpiredError) {
                    setUploadResult(SESSION_EXPIRED);
                    setWatchedRepoId(null);
                    setBusy(false);
                }
            }
        }

        check();
        pollRef.current = setInterval(check, POLL_MS);

        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
        };
    }, [watchedRepoId, rpProps.projectSelected.id]);

    // Egy futó import túléli a lap bezárását, ezért projektváltáskor és
    // újratöltéskor fel kell venni a fonalat ott, ahol abbamaradt.
    useEffect(() => {
        let cancelled = false;

        (async () => {
            try {
                const items = await loadRepos(rpProps.projectSelected.id);
                const running = items.find(r => !FINISHED.includes(r.status));
                if (cancelled || !running) return;

                setBusy(true);
                setUploadResult(describeRepo(running));
                setWatchedRepoId(running.id);
            } catch {
                // Induláskor egy sikertelen lekérdezés nem érdekes.
            }
        })();

        return () => { cancelled = true; };
    }, [rpProps.projectSelected.id]);

    const isProjOpen = !!rpProps.projOpen[rpProps.projectSelected.id];
    const files = filesByProjId[rpProps.projectSelected.id] ?? [];
    const tree = buildTree(files);
    return (<>
        <Drawer variant="persistent" anchor="right" open={open} sx={{
            width: open ? openWidth : closedWidth, gap: 2, "& .MuiDrawer-paper": {
                width: open ? openWidth : closedWidth,
                boxSizing: "border-box",
                top: HEADER_H,
                height: `calc(100% - ${HEADER_H}px)`,
            },
        }}>
            <Box sx={{
                display: "flex", justifyContent: "space-between", height: 56, alignItems: "center",
                marginLeft: 2, marginRight: 2
            }}>
                <Typography sx={{
                    lineHeight: 1,
                    fontFamily: "'Inter', sans-serif",
                }}>Files</Typography>
                <IconButton onClick={addFile}>+</IconButton>

            </Box>
            <List disablePadding dense>
                <div key={rpProps.projectSelected.id}>
                    <ListItemButton onClick={async () => {
                        await loadFiles(rpProps.projectSelected.id);
                        rpProps.setProjOpen(s => ({ ...s, [rpProps.projectSelected.id]: !s[rpProps.projectSelected.id] }));
                    }}>
                        <ListItemText primary={rpProps.projectSelected.name}></ListItemText>
                        {isProjOpen ? <ExpandMore /> : <ExpandLess />}

                    </ListItemButton>
                    <Collapse in={isProjOpen} timeout="auto" unmountOnExit>
                        <List disablePadding dense>
                            <FolderTree node={tree} level={1} onFileClick={() => { }}></FolderTree>
                        </List>
                    </Collapse>
                </div>
            </List>
        </Drawer>
        {rpProps.showWindowAddfile && <UploadFile setFile={setFile} link={link} open={rpProps.showWindowAddfile} setOpen={rpProps.setShowWindowAddFile}
            repo={repo} setRepo={setRepo} importRepo={importRepo} busy={busy} result={uploadResult} ></UploadFile>}
    </>);
}