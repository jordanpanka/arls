import SendIcon from "@mui/icons-material/Send";
import { Box, IconButton, Paper, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "preact/hooks";
import { NewConversation } from "./NewConversation";
type Message = {
    id: number,
    role: string,
    content: string

}
export type Conversation = {
    id: number,
    title: string,
    createdAtUtc: Date,
    updatedAtUtc: Date,
    messages: Message[]
}
type cProps = {
    newChat: boolean,
    setNewChat: (b: boolean) => void,
    selectedInvId:number,
    sellectedProjId: number,
    selectedCOnversationId: number,
    setSelectedConversationId: (id: number) => void,

}
export function ChatWindow(prop: cProps) {
    const [conversationsByProjId, setConversationsByProjId] = useState<Record<number, Conversation[]>>({});
    const [messagesByConvId, setMessagesByConvId] = useState<Record<number, Message[]>>({});
    const [prompt, setPrompt] = useState("");
    const [answer, setAnswer] = useState("kezdő");

    async function addConversation(title: string) {
        const projectId = prop.sellectedProjId;
        const token = localStorage.getItem("token");
        const response = await fetch("api/chat/conversations/add", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ projectId, title })
        })
        prop.setNewChat(false);
        const data = await response.json();
        prop.setSelectedConversationId(data);
    }

    async function addMessage(content: string, role: string) {
        const token = localStorage.getItem("token");
        const r = await fetch("api/chat/conversations/messages/add", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ convId: prop.selectedCOnversationId, content, role })
        })
        await loadMessages();
    }
    async function send() {
        await addMessage(prompt, "User")
        setAnswer("Thinking...");
        const token = localStorage.getItem("token");
        const r = await fetch("/api/chat/send", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ prompt, investigationId:prop.selectedInvId, projectId: prop.sellectedProjId}),
        });

        const data = await r.json();
        setAnswer(data.answer);
        setPrompt("");
        await addMessage(data.answer, "AI");


    }
    async function loadMessages() {
        const token = localStorage.getItem("token");
        const r = await fetch("api/chat/conversations/messages/load", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ id: prop.selectedCOnversationId })
        })

        const data = await r.json();
        setMessagesByConvId(prev => ({
            ...prev,
            [prop.selectedCOnversationId]: data
        }));
    }
    useEffect(() => { loadMessages(); }, [prop.selectedCOnversationId])
    return (<>
        {
            prop.selectedCOnversationId === -1 ? (
                <Paper
                    sx={{
                        flex: 1,
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        bgcolor: "transparent",
                        boxShadow: "none"
                    }}
                >
                    <Box
                        sx={{
                            textAlign: "center",
                            maxWidth: 520,
                            px: 4
                        }}
                    >
                        <Typography
                            variant="h4"
                            sx={{
                                fontWeight: 700,
                                mb: 2,
                                color: "#03045e"
                            }}
                        >
                            Welcome to Mini Chat
                        </Typography>

                        <Typography
                            sx={{
                                fontSize: 18,
                                color: "text.secondary",
                                mb: 3,
                                lineHeight: 1.6
                            }}
                        >
                            Organize your work into investigations and projects, upload your code, and start conversations to explore and understand your data.
                        </Typography>

                        <Box
                            sx={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 1.5,
                                px: 3,
                                py: 1.5,
                                borderRadius: 3,
                                bgcolor: "white",
                                boxShadow: 1
                            }}
                        >
                            <span style={{ fontSize: 22 }}>💬</span>
                            <Typography sx={{ fontWeight: 500 }}>
                                Start a new conversation
                            </Typography>
                        </Box>
                    </Box>
                </Paper>) :


                (<Paper
                    sx={{
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        minHeight: 0,
                        width: "100%",
                        overflow: "hidden"
                    }}>
                    {messagesByConvId[prop.selectedCOnversationId] != null &&
                        <Box sx={{
                            flex: 1,
                            minHeight: 0,
                            p: 2,
                            overflowY: "auto",

                        }}>
                            {messagesByConvId[prop.selectedCOnversationId].map(m => {
                                return <Box
                                    key={m.id}
                                    sx={{
                                        display: "flex",
                                        justifyContent: m.role === "User" ? "flex-end" : "flex-start",
                                        mr: "50px",
                                        ml: "50px"

                                    }}>
                                    <Paper
                                        sx={{
                                            //backgroundColor: m.role === "User" ? "white" : "#0077B6",
                                            margin: "1px",
                                            mt: "5px",
                                            mb: "5px"

                                        }}>
                                        <Typography sx={{ margin: "10px" }}>{m.content}</Typography>
                                    </Paper>
                                </Box>
                            })}

                        </Box>
                    }

                    <Box sx={{
                        display: "flex",
                        mr: "50px",
                        ml: "50px",
                        mb: "40px"
                    }}>
                        <TextField sx={{
                            width: "100%",
                            "& .MuiOutlinedInput-root": {
                                borderRadius: "16px"
                            }
                        }} value={prompt} onChange={(e) => { setPrompt(e.currentTarget.value) }} placeholder="What do you want to know?"></TextField>
                        <IconButton onClick={send}><SendIcon /></IconButton>
                    </Box>

                </Paper>)
        }
        {prop.newChat && <NewConversation open={prop.newChat} setOpen={prop.setNewChat} addConversation={addConversation}></NewConversation>}
    </>
    );

}