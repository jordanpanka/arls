import { useState } from "preact/hooks";
import { ProjectBar } from "../layout/ProjectBar";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField, Typography } from "@mui/material";

type npProps = {
    isInv: boolean,
    invId?: number,
    open: boolean,
    setOpen: (b: boolean) => void,
    loadInvestigations: () => void,
    loadProjects:(id:number)=>void
}
export function NewProject(props: npProps) {
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    async function addInvestigation() {
        const token = localStorage.getItem("token");
        const response = await fetch("api/investigations/add", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token

            },
            body: JSON.stringify({ name, description })
        })

        props.setOpen(false);
        await props.loadInvestigations();
    }
    async function addProject() {
        if (props.invId == null) return;
        const invid = props.invId;
        const token = localStorage.getItem("token");
        const response = await fetch("api/investigations/projects/add", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ invid, name, description })
        })
        props.setOpen(false);
        await props.loadProjects(invid);

    }
    return (<>
        <Dialog open={props.open} onClose={() => props.setOpen(false)}>
            <DialogTitle>{props.isInv ? "New Investigation" : "New Project"}</DialogTitle>
            <DialogContent>
                <TextField value={name} placeholder="Name" onChange={e=>{setName(e.currentTarget.value)}}></TextField>
                <TextField value={description} placeholder="Description" onChange={e=>{setDescription(e.currentTarget.value)}}></TextField>
            </DialogContent>
            <DialogActions>
                <Button onClick={() => props.setOpen(false)}>Cancel</Button>
                <Button onClick={props.isInv ? addInvestigation : addProject}>Create</Button>
            </DialogActions>
        </Dialog>
    </>);
}