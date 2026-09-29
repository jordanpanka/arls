using ef;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using System.Drawing;
[ApiController]
[Route("/api/chat")]
public class ChatController : ControllerBase
{
    private readonly ChatService chatService;

    public ChatController(ChatService cservice)
    {
        chatService=cservice;
    }

    [Authorize]
    [HttpPost("conversations/add")]
    public async Task<IActionResult> AddConversation([FromBody]ConversationData data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        var result=await chatService.AddConversationAsync(data);
        if(!result.Ok)return BadRequest();
        return Ok(result.Data);
    }

    [Authorize]
    [HttpPost("conversations/load")]
    public async Task<IActionResult> LoadConversations([FromBody]ProjectID projectId)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        var result=await chatService.LoadConversationsAsync(projectId);
        if(!result.Ok) return BadRequest();
       // Console.WriteLine(result.Data == null ? "NULL" : result.Data.ToString());
        return Ok(result.Data);

    }

    [Authorize]
    [HttpPost("conversations/delete")]
    public async Task<IActionResult> DeleteConversation([FromBody] Id data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        var result=await chatService.DeleteConversationAsync(data);
        if(!result.Ok) return BadRequest(result.Error);
        return Ok();
    }

    [Authorize]
    [HttpPost("conversations/rename")]
    public async Task<IActionResult> RenameConversation([FromBody] RenameData data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        var result=await chatService.RenameConversationAsync(data);
        if(!result.Ok) return BadRequest(result.Error);
        return Ok();
    }
    [Authorize]
    [HttpPost("conversations/messages/add")]

    public async Task<IActionResult> AddMessage([FromBody] MessageData data)
    {
        var uidClaim=User.FindFirst("uid")?.Value;
        if(uidClaim==null) return Unauthorized();

        var result=await chatService.AddMessageAsync(data);
        if(!result.Ok) return BadRequest();
        return Ok();
    }

    [Authorize]
    [HttpPost("conversations/messages/load")]

    public async Task<IActionResult> LoadMessage([FromBody] Id data)
    {
        var uidClaim=User.FindFirst("uid")?.Value;
        if(uidClaim==null) return Unauthorized();

        var result=await chatService.LoadMessagesAsync(data);
        if(!result.Ok)return BadRequest();
        return Ok(result.Data);
    }

    [Authorize]
    [HttpPost("send")]
    public async Task<IActionResult> SendMessage([FromBody] ChatRequest prompt)
    {
        var uidClaim=User.FindFirst("uid")?.Value;
        if(uidClaim==null) return Unauthorized();

        var result=await chatService.SendMessageAsync(int.Parse(uidClaim),prompt);
        //Console.WriteLine("BOLDOGSÁÁÁÁÁÁÁG\n");
       // if(!result.Ok) return BadRequest(result.Error);
        if (!result.Ok) return BadRequest(new { error = result.Error });
        return Ok(result.Data);
    }

}
