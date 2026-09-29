public class ServiceResult
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public object? Data { get; set; }
    public static ServiceResult Success(object data = null)
     => new ServiceResult { Ok = true, Data = data };

    public static ServiceResult Fail(string error)
    => new ServiceResult { Ok = false, Error = error };
}