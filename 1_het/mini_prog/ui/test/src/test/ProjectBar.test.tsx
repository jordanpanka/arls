import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ProjectBar } from "../components/layout/ProjectBar";

vi.mock("@mui/material", () => ({
  Box: (p: any) => <div>{p.children}</div>,
  Collapse: (p: any) => (p.in ? <div>{p.children}</div> : null),
  IconButton: (p: any) => <button onClick={p.onClick}>{p.children}</button>,
  InputAdornment: (p: any) => <span>{p.children}</span>,
  List: (p: any) => <div>{p.children}</div>,
  ListItemButton: (p: any) => <button onClick={p.onClick}>{p.children}</button>,
  ListItemText: (p: any) => <span>{p.primary}</span>,
  TextField: (p: any) => (
    <input
      placeholder={p.placeholder}
      value={p.value}
      onInput={p.onChange}
    />
  ),
  Tooltip: (p: any) => <div>{p.children}</div>,
  Typography: (p: any) => <div>{p.children}</div>,
}));

vi.mock("@mui/material/Drawer", () => ({
  default: (p: any) => <div>{p.children}</div>,
}));

vi.mock("@mui/icons-material/CreateNewFolder", () => ({
  default: () => <span>folder</span>,
}));

vi.mock("@mui/icons-material/Diamond", () => ({
  default: () => <span>diamond</span>,
}));

vi.mock("@mui/icons-material/DiamondOutlined", () => ({
  default: () => <span>diamond-outlined</span>,
}));

vi.mock("@mui/icons-material/ChatBubble", () => ({
  default: () => <span>chat</span>,
}));

vi.mock("@mui/icons-material/Search", () => ({
  default: () => <span>search</span>,
}));

vi.mock("@mui/icons-material/MoreHoriz", () => ({
  default: () => <span>more</span>,
}));

vi.mock("../RowMenu", () => ({
  RowMenu: () => <div>RowMenu</div>,
}));

vi.mock("../NewProject", () => ({
  NewProject: (p: any) => (
    <div>
      {p.isInv ? "New Investigation Window" : "New Project Window"}
    </div>
  ),
}));

vi.mock("../FolderTree", () => ({
  buildTree: () => ({ name: "root", folders: [], files: [] }),
  FolderTree: () => <div>FolderTree</div>,
}));

describe("ProjectBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem("token", "test-token");

    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "api/investigations/load") {
        return Promise.resolve({
          json: () => Promise.resolve([
            { id: 1, name: "Investigation 1", description: "desc" },
          ]),
        });
      }

      if (url === "api/investigations/projects/load") {
        return Promise.resolve({
          json: () => Promise.resolve([
            { id: 10, invid: 1, name: "Project 1", description: "desc" },
          ]),
        });
      }

      return Promise.resolve({
        json: () => Promise.resolve([]),
      });
    }));
  });

  function renderProjectBar() {
    return render(
      <ProjectBar
        setSelectedProject={vi.fn()}
        selectedProjectId={-1}
        setSelectedProjectId={vi.fn()}
        shoWindowFile={false}
        setShowWindowFile={vi.fn()}
        conversatuionsByProjId={{
          10: [{ id: 100, projectId: 10, title: "Conversation 1" } as any],
        }}
        loadConversations={vi.fn()}
        newConv={false}
        setNewConv={vi.fn()}
        selectedConversationId={-1}
        setSelectedConversationId={vi.fn()}
        selectedInvId={-1}
        setSelectedInvId={vi.fn()}
      />
    );
  }

  it("betölti és megjeleníti az investigation listát", async () => {
    renderProjectBar();

    await waitFor(() => {
      expect(screen.getByText("Investigation 1")).toBeInTheDocument();
    });
  });

  it("investigation kattintásra betölti a projekteket", async () => {
    const setSelectedInvId = vi.fn();

    render(
      <ProjectBar
        setSelectedProject={vi.fn()}
        selectedProjectId={-1}
        setSelectedProjectId={vi.fn()}
        shoWindowFile={false}
        setShowWindowFile={vi.fn()}
        conversatuionsByProjId={{}}
        loadConversations={vi.fn()}
        newConv={false}
        setNewConv={vi.fn()}
        selectedConversationId={-1}
        setSelectedConversationId={vi.fn()}
        selectedInvId={-1}
        setSelectedInvId={setSelectedInvId}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Investigation 1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Investigation 1"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "api/investigations/projects/load",
        expect.objectContaining({ method: "POST" })
      );
      expect(setSelectedInvId).toHaveBeenCalledWith(1);
    });
  });

  it("plusz gombra megnyitja az új investigation ablakot", async () => {
    renderProjectBar();

    fireEvent.click(screen.getByText("+"));

    expect(screen.getByText("New Investigation Window")).toBeInTheDocument();
  });
});