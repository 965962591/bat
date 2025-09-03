from __future__ import print_function
import os
import re
from collections import defaultdict
import itertools
import time
import heapq
import codecs


accepted_log_ext = (".txt", ".log")


def merge_in_memory(file_handles, output_file, filter_override, mode):
    # Load every file into one massive list
    all_in_one = []
    current = 0
    for fh in file_handles:
        current += 1
        print(
            "\rReading log {}/{} of current session".format(current, len(file_handles)),
            end="",
        )
        all_in_one.extend(fh.readlines())
        fh.close()

    # Delete reference to file handles to ensure resources are freed
    del file_handles

    # Sort the list by timestamp and filter out lines that don't start with a timestamp
    print()
    print("Merging")
    all_in_one.sort()
    all_in_one = filter(lambda line: (line[0] >= "0" and line[0] <= "9"), all_in_one)

    # Write to output file
    with open(output_file, mode) as output:
        output.writelines(all_in_one)


def iterative_merge(file_handles, output_file, filter_override, mode):
    # Iteratively merge and write at the same time
    with open(output_file, mode) as output:
        print("Merging")
        for line in heapq.merge(*file_handles):
            if line[0] >= "0" and line[0] <= "9":
                output.write(line)

    # Free file resources
    for fh in file_handles:
        fh.close()
    del file_handles


def second_pass_merge(merged_offline, other_fhs, output_file):
    merged_offline_fh = codecs.open(merged_offline, "r", errors="ignore")
    file_handles = [merged_offline_fh] + list(map(pad_timestamp, other_fhs))
    with open(output_file, "w") as output:
        for line in heapq.merge(*file_handles):
            output.write(line)

    merged_offline_fh.close()
    for fh in other_fhs:
        fh.close()
    try:
        os.remove(merged_offline)
    except:
        print("Unable to delete")


def pad_timestamp(file_handle):
    duplicate_filter = "(I|E|W) (CamX\s*:|CHIUSECASE\s*:)"
    re_duplicate = re.compile(duplicate_filter)
    re_timestamp = re.compile("^[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}.(\d+)")
    offline_precision = 9  # Number of digits to represent microseconds
    for line in file_handle:
        if line[0] >= "0" and line[0] <= "9":
            if re_duplicate.search(line):
                continue

            timestamp_match = re_timestamp.match(line)
            if timestamp_match and len(timestamp_match.group(1)) < offline_precision:
                num_digits_needed = offline_precision - len(timestamp_match.group(1))
                preline = line[: timestamp_match.start(1) - 1]
                postline = line[timestamp_match.end(1) :]
                padded = "{}:{}{}{}".format(
                    preline, timestamp_match.group(1), "0" * num_digits_needed, postline
                )
                yield padded
            else:
                yield line


def pad_timestamps(file_handles, duplicate_filter=None):
    for fh in file_handles:
        yield pad_timestamp(fh, duplicate_filter)


def filter_lines(file_handle):
    for line in file_handle:
        if line[0] >= "0" and line[0] <= "9":
            yield line
    file_handle.close()


def filter_files(file_handles):
    for fh in file_handles:
        yield filter_lines(fh)


def iterative_merge2(file_handles, output_file, filter_override, mode):
    with open(output_file, mode) as output:
        output.writelines(heapq.merge(*filter_files(file_handles)))


def opening_hook(encoding, errors=None):
    import io

    def openhook(filename, mode):
        print("Opening {}".format(filename))
        return io.open(filename, "r", encoding=encoding, newline="", errors=errors)

    return openhook


def main(input_directory, output_file):
    # Define filter override (Useful if merging logs that may not begin with a timestamp)
    filter_override = r"\d+"

    if not os.path.isdir(input_directory):
        exit("Invalid input directory")

    # Look at the set of logs to be merged and organize them into log_files datastructure
    log_info = re.compile("Camx_OfflineLog.*Tid(\d+)_Session(\d+)_Segment(\d+)")
    print("Discovering log files in: {}".format(input_directory))
    log_files = defaultdict(lambda: defaultdict(list))
    other_files = []
    num_ascii = 0
    num_other = 0
    for log_file in [
        filepath
        for filepath in os.listdir(input_directory)
        if filepath.endswith(".txt")
    ]:
        session_match = log_info.search(log_file)
        log_path = os.path.join(input_directory, log_file)
        if session_match:
            (thread_id, session_id, segment_id) = session_match.groups()
            log_files[session_id][thread_id].append(log_path)
            num_ascii += 1
        elif log_file.endswith(accepted_log_ext):
            other_files.append(log_path)
            num_other += 1
        else:
            print(
                "Skipping {} because has an invalid filetype. Needs to be {}".format(
                    log_file, accepted_log_ext
                )
            )

    # Begin sorting each session
    print("Found {} files from {} sessions".format(num_ascii, len(log_files.keys())))
    if num_other > 0:
        print("Also found {} non offline ascii logs to be merged".format(num_other))
    max_session_size = 2 * (
        10**9
    )  # Max size in GB (Whether to use memory merge or iterative merge)
    total_start_time = time.time()
    first_write = True
    output_files = []
    for session_id in sorted(log_files.keys(), key=int):
        start_time = time.time()
        session_size = 0
        for thread_id in log_files[session_id].keys():
            for log_file in log_files[session_id][thread_id]:
                session_size += os.stat(log_file).st_size

        mode = "w"
        if num_other == 0:
            output_file_temp = output_file
        else:
            # We'll be performing a second-pass merge, so don't write to final output file just yet
            output_file_temp = os.path.join(
                os.path.dirname(output_file), "~" + os.path.basename(output_file)
            )
        output_files.append(output_file_temp)
        if not first_write:
            mode = "a"

        file_handles = [
            codecs.open(log_file, "r", errors="ignore")
            for log_file in itertools.chain(*log_files[session_id].values())
        ]
        memory_ok = session_size <= max_session_size
        print(
            "Merging session {} with {} merge".format(
                session_id, "in_memory" if memory_ok else "iterative"
            )
        )
        if memory_ok:
            merge_in_memory(file_handles, output_file_temp, filter_override, mode)
        else:
            iterative_merge(file_handles, output_file_temp, filter_override, mode)

        print("Done ({}s)".format(round(time.time() - start_time, 2)))
        first_write = False

    if num_other > 0:
        second_pass_start = time.time()
        print("Merging other files")
        other_fhs = [
            codecs.open(log_file, "r", errors="ignore") for log_file in other_files
        ]
        second_pass_merge(output_file_temp, other_fhs, output_file)
        print("Done ({}s)".format(round(time.time() - second_pass_start, 2)))
    else:
        # Rename the temporary output file to the final output file name
        os.rename(output_file_temp, output_file)

    print(
        "Output: {} Complete ({}s)".format(
            output_file, round(time.time() - total_start_time, 3)
        )
    )
    return 0


# if __name__ == '__main__':
#     # Example usage
#     main('D:\\tuning\\tools\\log\\camera', 'out.txt')
