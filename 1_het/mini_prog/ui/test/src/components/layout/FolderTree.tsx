import { ExpandLess, ExpandMore, } from "@mui/icons-material";
import { ListItemText, ListItemButton, Collapse, List, } from "@mui/material";
import { useState } from "preact/hooks";
import FolderIcon from "@mui/icons-material/Folder";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";

export type FileItem = { 
 id:number,
 name:string,
 relativePath:string,
 }
export type FolderNode = {
    id: string,
    name: string,
    folders: FolderNode[],
    files: FileItem[]
}
 export function buildTree(files: FileItem[]): FolderNode {
        const root: FolderNode = { id: "root", name: "root", folders: [], files: [] }
        function getOrCreatefolder(parent: FolderNode, name: string) {
            let f = parent.folders.find(x => x.name == name);
            if (!f) {
                f = { id: parent.id + "/" + name, name, folders: [], files: [] };
                parent.folders.push(f);
            }
            return f;
        }
        for (const f of files) {
            const parts = f.relativePath.split("/").filter(Boolean);
            const fileName = parts.pop()!;
            let current = root;

            for (const folderName of parts) current = getOrCreatefolder(current, folderName);

            current.files.push({ id: f.id, name: fileName, relativePath: f.relativePath })
        }
        const sortNode = (node: FolderNode) => {
            node.folders.sort((a, b) => a.name.localeCompare(b.name));
            node.files.sort((a, b) => a.name.localeCompare(b.name))
            node.folders.forEach(sortNode)
        }
        return root;

    }
export function FolderTree({ node, level, onFileClick, }: { node: FolderNode, level: number, onFileClick: (file: FileItem) => void }) {
    const hasChildren = node.folders.length > 0 || node.files.length > 0;
    const [open, setOpen] = useState(level <= 1);

    return (<>
        {node.id !== "root" && (
            <ListItemButton
                sx={{ pl: 2 + level * 2 }}
                onClick={() => hasChildren && setOpen(!open)}
                disabled={!hasChildren}
            >
                
                📁
                <ListItemText primary={node.name} />
                {hasChildren ? (open ? <ExpandLess /> : <ExpandMore />) : null}
            </ListItemButton>
        )}
        <Collapse in={node.id === "root" ? true : open} timeout="auto" unmountOnExit>
            <List disablePadding dense>
                {node.folders.map((f) => (
                    <FolderTree key={f.id} node={f} level={level + 1} onFileClick={onFileClick} />
                ))}
            </List>
            {node.files.map(file => (
                <ListItemButton key={file.id} sx={{ pl: 2 + (level + 1) * 2 }} onClick={() => { onFileClick(file) }}>
                   
                    📄
                    <ListItemText primary={file.name} />

                </ListItemButton>
            ))}
        </Collapse>

    </>);
}