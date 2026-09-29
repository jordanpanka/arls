import { Box, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import { useState } from "preact/hooks";
import type { Dispatch } from "preact/hooks";

export type RepoForm = {
    owner: string,
    name: string,
    reference: string
};

type UploadFileProps = {
    setFile: Dispatch<FileList>,
    link: () => Promise<void>,
    open: boolean,
    setOpen: (b: boolean) => void,
    repo: RepoForm,
    setRepo: (r: RepoForm) => void,
    importRepo: () => Promise<void>,
    busy: boolean,
    result: string
};

function tabStyle(active: boolean) {
    return {
        flex: 1,
        padding: "8px",
        cursor: "pointer",
        background: "none",
        border: "none",
        borderBottom: active ? "2px solid #1976d2" : "2px solid transparent",
        fontWeight: active ? 600 : 400
    };
}

export function UploadFile({ setFile, link, open, setOpen, repo, setRepo, importRepo, busy, result }: UploadFileProps) {
    const [tab, setTab] = useState<"files" | "repo">("files");

    return (
        <Dialog open={open} onClose={() => setOpen(false)}>
            <DialogTitle></DialogTitle>
            <DialogContent >
                <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>

                    <div style={{ display: "flex" }}>
                        <button style={tabStyle(tab === "files")} onClick={() => setTab("files")}>
                            Local files
                        </button>
                        <button style={tabStyle(tab === "repo")} onClick={() => setTab("repo")}>
                            GitHub repository
                        </button>
                    </div>

                    {tab === "files" ? (
                        <>
                            <label>Choose files</label>
                            <input
                                type="file"
                                multiple
                                onChange={(e) => {
                                    const files = e.currentTarget.files;
                                    if (files) setFile(files);
                                }}
                            />

                            <label>Choose a directory</label>
                            <input
                                type="file"
                                multiple
                                //@ts-ignore
                                webkitdirectory
                                onChange={(e) => {
                                    const files = e.currentTarget.files;
                                    if (files) setFile(files);
                                }}
                            />
                        </>
                    ) : (
                        <>
                            <label>Owner</label>
                            <input
                                type="text"
                                value={repo.owner}
                                placeholder="octocat"
                                onInput={(e) => setRepo({ ...repo, owner: e.currentTarget.value })}
                            />

                            <label>Repository</label>
                            <input
                                type="text"
                                value={repo.name}
                                placeholder="Hello-World"
                                onInput={(e) => setRepo({ ...repo, name: e.currentTarget.value })}
                            />

                            <label>Branch, tag or commit</label>
                            <input
                                type="text"
                                value={repo.reference}
                                placeholder="HEAD"
                                onInput={(e) => setRepo({ ...repo, reference: e.currentTarget.value })}
                            />
                        </>
                    )}

                    {/* Az import a backend háttérszálán fut, és percekig is tarthat.
                        A busy flaget a RightPanel pollozása veszi vissza, amikor a
                        státusz Ready vagy Failed lesz — enélkül lefagyottnak tűnne. */}
                    {busy && <span>Import in progress…</span>}
                    {result && <span>{result}</span>}

                </Box>
            </DialogContent>
            <DialogActions>
                <button disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
                {tab === "files"
                    ? <button disabled={busy} onClick={link}>Upload</button>
                    : <button disabled={busy} onClick={importRepo}>Import</button>}
            </DialogActions>
        </Dialog>
    );
}
