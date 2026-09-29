import { Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from "@mui/material";
import { useState } from "preact/hooks";
type ncProps = {
    open: boolean,
    setOpen: (b: boolean) => void,
    addConversation:(s:string)=>void
}
export function NewConversation(props: ncProps) {
    const [name,setName]=useState("");
    return (<>
        <Dialog open={props.open} onClose={() => props.setOpen(false)}>
            <DialogTitle>{"New Conversation"}</DialogTitle>
            <DialogContent>
                <TextField value={name} placeholder="Name" onChange={e => { setName(e.currentTarget.value) }}></TextField>
            </DialogContent>
            <DialogActions>
                <Button onClick={() => props.setOpen(false)}>Cancel</Button>
                <Button onClick={()=>props.addConversation(name)}>Create</Button>
            </DialogActions>
        </Dialog>
    </>);
}