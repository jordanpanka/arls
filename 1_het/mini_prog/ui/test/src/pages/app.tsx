import { useEffect, useRef, useState } from 'preact/hooks'
import '../styles/app.css';
import { ProjectBar, type Project } from '../components/layout/ProjectBar';
import { AppBar, Avatar, Box, IconButton, Toolbar, Typography } from '@mui/material';
import LogoutIcon from "@mui/icons-material/Logout";
import { jwtDecode as decodeJwt } from "jwt-decode";
import { useLocation } from "preact-iso";
import { RightPanel } from '../components/layout/RightPanel';
import { type Conversation } from '../components/chat/Chat';
import { ChatArea } from '../components/chat/ChatArea';

// Same value the sidebars use, so everything starts right below the AppBar.
const HEADER_H = 64;
export type JwtPayload = {
  uid: string
  email: string
  firstname: string
  lastname: string
}
export function App() {
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("bla bla bla");
  const [file, setFile] = useState<FileList>();
  const [showWindowFile, setShowwindowFile] = useState(false);
  const [uploadResult, setUploadResult] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  //variables for sidebars
  const [conversationsByProjId, setConversationsByProjId] = useState<Record<number, Conversation[]>>({});
  const [projOpen, setProjOpen] = useState<Record<number, boolean>>({});
  const [selectedProject, setSelectedProject] = useState<Project>();
  const [selectedConversationId, setSelectedConversationId] = useState<number>(-1);
  const [selectedProjectId, setSelectedProjectId] = useState<number>(-1);
  const [selectedInvestigationId, setSelectedInvestigationId] = useState<number>(-1);
  const { route } = useLocation();

  const [isnewConversation, setIsNewConversation] = useState(false)
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const sidebarsBeforeEvidence = useRef<{ left: boolean, right: boolean } | null>(null);

  // The evidence panel needs the room, so the sidebars step aside while it is open.
  function handleEvidencePanel(open: boolean) {
    if (open && !sidebarsBeforeEvidence.current) {
      sidebarsBeforeEvidence.current = { left: leftOpen, right: rightOpen };
      setLeftOpen(false);
      setRightOpen(false);
    } else if (!open && sidebarsBeforeEvidence.current) {
      setLeftOpen(sidebarsBeforeEvidence.current.left);
      setRightOpen(sidebarsBeforeEvidence.current.right);
      sidebarsBeforeEvidence.current = null;
    }
  }
  useEffect(() => {
    if (!localStorage.getItem("token")) {
      route("/login");
    }
  }, []);
  async function send() {
    setAnswer("Thinking...");

    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    const data = await r.json();
    setAnswer(data.answer);
  }


  async function link() {
    if (!file) {
      setUploadResult("Előbb válassz ki egy fájlt!");
      return;
    }

    const data = new FormData();
    for (const f of Array.from(file ?? [])) {
      data.append("files", f);
      data.append("paths", f.webkitRelativePath);
    }
    const token = localStorage.getItem("token");
    const response = await fetch("/api/investigations/projects/files/upload", {
      method: "POST",
      headers: { "Authorization": "Bearer " + token },
      body: data
    })
    setShowwindowFile(false);

  }
  function setName() {
    const token = localStorage.getItem("token");
    if (!token) return; // nincs bejelentkezve

    const decoded = decodeJwt<JwtPayload>(token);

    setFirstName(decoded.firstname);
    setLastName(decoded.lastname);
  }
  function logout() {

    localStorage.removeItem("token");
    route("/login", true);
  }
  useEffect(() => setName(), []);
  async function loadConversations(id: number) {
    const token = localStorage.getItem("token");
    //const id = selectedProject?.id;
    const response = await fetch("api/chat/conversations/load", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
      },
      body: JSON.stringify({ id })
    })
    const data = await response.json();
    if (id) {
      setConversationsByProjId(prev => ({
        ...prev,
        [id]: data
      }));
    }
  }
  return (
    <>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          backgroundColor: "white",
          color: "black",
          borderBottom: "1px solid #eee",
          zIndex: (theme) => theme.zIndex.drawer + 1,
        }}
      >
        <Toolbar sx={{ height: HEADER_H, minHeight: `${HEADER_H}px !important`, backgroundColor: "#03045e" }}>
          <Box sx={{ display: 'flex', alignItems: "center", justifyContent: "space-between", width: "100%" }}>
            <Typography sx={{ fontWeight: 600, fontSize: 30, color: "white" }}>
              Code Mind
            </Typography>
            <Box sx={{ display: 'flex', alignItems: "center", gap: 2 }}>
              <Avatar
                sx={{
                  width: 40,
                  height: 40,
                  bgcolor: "#88B8F9",
                  color: "white",
                  fontWeight: 700,
                  fontSize: 20
                }}
              >
                {firstName?.charAt(0).toUpperCase()}
              </Avatar>
              <Typography sx={{ color: "white" }}>
                {lastName} {firstName}
              </Typography>
              <IconButton onClick={logout}>
                <LogoutIcon sx={{ color: "white" }} />
              </IconButton>
            </Box>
          </Box>
        </Toolbar>
      </AppBar>

      <Box
        sx={{
          display: "flex",
          height: `calc(100vh - ${HEADER_H}px)`,
          mt: `${HEADER_H}px`,
          overflow: "hidden",
          minHeight: 0
        }}
      >
        <ProjectBar
          setSelectedProject={setSelectedProject}
          selectedProjectId={selectedProjectId}
          setSelectedProjectId={setSelectedProjectId}
          shoWindowFile={showWindowFile}
          setShowWindowFile={setShowwindowFile}
          loadConversations={loadConversations}
          conversatuionsByProjId={conversationsByProjId}
          newConv={isnewConversation}
          setNewConv={setIsNewConversation}
          selectedConversationId={selectedConversationId}
          setSelectedConversationId={setSelectedConversationId}
          selectedInvId={selectedInvestigationId}
          setSelectedInvId={setSelectedInvestigationId}
          open={leftOpen}
          onToggle={() => setLeftOpen(o => !o)}
        />

        <Box
          sx={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            display: "flex",
            justifyContent: "center",
            width: "100%",
            overflow: 'hidden'

          }}
        >
          {/*selectedProjectId!=-1 && */(
            <ChatArea
              newChat={isnewConversation}
              setNewChat={setIsNewConversation}
              sellectedProjId={selectedProjectId}
              selectedInvId={selectedInvestigationId}
              selectedCOnversationId={selectedConversationId}
              setSelectedConversationId={setSelectedConversationId}
              onPanelOpenChange={handleEvidencePanel}
            />
          )}
        </Box>

        {selectedProject && selectedProjectId != -1 && (
          <RightPanel
            selectedInvId={selectedInvestigationId}
            projectSelected={selectedProject}
            projOpen={projOpen}
            setProjOpen={setProjOpen}
            showWindowAddfile={showWindowFile}
            setShowWindowAddFile={setShowwindowFile}
            open={rightOpen}
            onToggle={() => setRightOpen(o => !o)}
          />
        )}
      </Box>
    </>
  );
}

