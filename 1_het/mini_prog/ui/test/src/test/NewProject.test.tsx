import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NewProject } from "../components/project/NewProject";

vi.mock("@mui/material", () => ({
  Dialog: (p: any) => (p.open ? <div>{p.children}</div> : null),
  DialogTitle: (p: any) => <h2>{p.children}</h2>,
  DialogContent: (p: any) => <div>{p.children}</div>,
  DialogActions: (p: any) => <div>{p.children}</div>,
  TextField: (p: any) => (
    <input
      placeholder={p.placeholder}
      value={p.value}
      onInput={p.onChange}
    />
  ),
  Button: (p: any) => <button onClick={p.onClick}>{p.children}</button>,
  Typography: (p: any) => <div>{p.children}</div>,
}));

describe("NewProject", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem("token", "test-token");
  });

  it("New Investigation dialogot jelenít meg", () => {
    render(
      <NewProject
        isInv={true}
        open={true}
        setOpen={vi.fn()}
        loadInvestigations={vi.fn()}
        loadProjects={vi.fn()}
      />
    );

    expect(screen.getByText("New Investigation")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Description")).toBeInTheDocument();
  });

  it("Cancel gombra bezár", () => {
    const setOpen = vi.fn();

    render(
      <NewProject
        isInv={true}
        open={true}
        setOpen={setOpen}
        loadInvestigations={vi.fn()}
        loadProjects={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Cancel"));

    expect(setOpen).toHaveBeenCalledWith(false);
  });

  it("létrehoz investigationt", async () => {
    const setOpen = vi.fn();
    const loadInvestigations = vi.fn();

    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({}),
      })
    ));

    render(
      <NewProject
        isInv={true}
        open={true}
        setOpen={setOpen}
        loadInvestigations={loadInvestigations}
        loadProjects={vi.fn()}
      />
    );

    fireEvent.input(screen.getByPlaceholderText("Name"), {
      target: { value: "Teszt investigation" },
    });

    fireEvent.input(screen.getByPlaceholderText("Description"), {
      target: { value: "Leírás" },
    });

    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "api/investigations/add",
        expect.objectContaining({ method: "POST" })
      );
      expect(setOpen).toHaveBeenCalledWith(false);
      expect(loadInvestigations).toHaveBeenCalled();
    });
  });

  it("létrehoz projektet", async () => {
    const loadProjects = vi.fn();

    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({}),
      })
    ));

    render(
      <NewProject
        isInv={false}
        invId={5}
        open={true}
        setOpen={vi.fn()}
        loadInvestigations={vi.fn()}
        loadProjects={loadProjects}
      />
    );

    fireEvent.input(screen.getByPlaceholderText("Name"), {
      target: { value: "Teszt projekt" },
    });

    fireEvent.input(screen.getByPlaceholderText("Description"), {
      target: { value: "Projekt leírás" },
    });

    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "api/investigations/projects/add",
        expect.objectContaining({ method: "POST" })
      );
      expect(loadProjects).toHaveBeenCalledWith(5);
    });
  });
});