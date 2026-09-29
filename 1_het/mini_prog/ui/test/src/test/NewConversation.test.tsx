import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";
import { NewConversation } from "../components/chat/NewConversation";

vi.mock("@mui/material", () => ({
  Dialog: (props: any) => props.open ? <div>{props.children}</div> : null,
  DialogTitle: (props: any) => <h2>{props.children}</h2>,
  DialogContent: (props: any) => <div>{props.children}</div>,
  DialogActions: (props: any) => <div>{props.children}</div>,
  TextField: (props: any) => (
    <input
      placeholder={props.placeholder}
      value={props.value}
      onInput={props.onChange}
    />
  ),
  Button: (props: any) => <button onClick={props.onClick}>{props.children}</button>,
}));

describe("NewConversation", () => {
  it("megjeleníti a dialogot", () => {
    render(
      <NewConversation
        open={true}
        setOpen={vi.fn()}
        addConversation={vi.fn()}
      />
    );

    expect(screen.getByText("New Conversation")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
  });

  it("Cancel gombra bezárja az ablakot", () => {
    const setOpen = vi.fn();

    render(
      <NewConversation
        open={true}
        setOpen={setOpen}
        addConversation={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Cancel"));

    expect(setOpen).toHaveBeenCalledWith(false);
  });

  it("Create gombra meghívja az addConversation függvényt", () => {
    const addConversation = vi.fn();

    render(
      <NewConversation
        open={true}
        setOpen={vi.fn()}
        addConversation={addConversation}
      />
    );

    fireEvent.input(screen.getByPlaceholderText("Name"), {
      target: { value: "Új beszélgetés" },
    });

    fireEvent.click(screen.getByText("Create"));

    expect(addConversation).toHaveBeenCalledWith("Új beszélgetés");
  });
});