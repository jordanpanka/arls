import { Menu, MenuItem } from "@mui/material";

type rmProps = {
    anchor: HTMLElement | null,
    setAnchor: (a: HTMLElement | null) => void,
    addFile: () => void,
    addProj: () => void,
    type: "project" | "file" | "conversation" |"investigation" | null,
    deleteInv: () => void,
    deleteProj: () => void,
    deleteConv: () => void,
    rename:()=>void,
    addConversation: () => void
}
export function RowMenu(prop: rmProps) {
    async function handleAddClick() {
        switch (prop.type) {
            case "investigation":
                prop.addProj();
                return;
            case "project":
                prop.addFile();
                return;
        }
    }
    async function deleteClick() {
        switch (prop.type) {
            case "investigation":

                await prop.deleteInv();
                return;
            case "project":

                await prop.deleteProj();
                return;

            case "conversation":
                await prop.deleteConv();
                return;

        }

    }
    function getNewLabel():string{
        switch (prop.type) {
            case "investigation":
                return "Add new Project";
            case "project":
                return "Add new File";
            case "conversation":
                return "Add new File";
            default:
                return "";
        }
                
    }
    async function run(action:()=>void){
        action();
        prop.setAnchor(null);
    }
    return (
        <Menu anchorEl={prop.anchor} open={!!prop.anchor} onClose={() => prop.setAnchor(null)}>
            {prop.type == "project" && <MenuItem onClick={prop.addConversation}>Add new conversation</MenuItem>}
            <MenuItem onClick={()=>run(handleAddClick)}>{getNewLabel()}</MenuItem>
            <MenuItem onClick={()=>run(prop.rename)}>Rename</MenuItem>
            <MenuItem onClick={()=>run(deleteClick)}>Delete</MenuItem>
        </Menu>
    );
}