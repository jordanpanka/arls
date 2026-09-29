public record ConversationData(int projectId, string title);
public record Id(int id);

public record MessageData(int convId, string content, string role);
public record Ids( int invId, int projectId); 
public record FilesData(int id, int projectId);
public record ProjectData(int invid, string name, string description);
public record InvestigationData(string name, string description);
public record UserID(int id);
public record InvestigationID(int id);
public record ProjectID(int id);

public record RenameData(int id, string name);
public record ChatRequest(string prompt, int investigationId, int projectId);
public record ChatRequestPython(string prompt,int userId, int investigationId, int projectId);
public record RegisterData(string email, string password, string firstName, string lastName);